"""
Authentication & user management endpoints.
"""
import uuid
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from story_spec.db.models import User, RefreshToken, APIToken, AuditLog, AuditLogAction
from story_spec.db.session import get_db
from story_spec.api.deps import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_active_user,
)
from story_spec.db.models import pwd_context

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Pydantic schemas ──────────────────────────────────────────────────


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    login: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str
    full_name: Optional[str]
    is_active: bool
    email_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class APITokenCreate(BaseModel):
    name: str


class APITokenResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]


class APITokenCreated(BaseModel):
    id: uuid.UUID
    name: str
    token: str
    created_at: datetime


class MessageResponse(BaseModel):
    message: str


# ── Helpers ───────────────────────────────────────────────────────────


def _create_audit_log(
    db: Session,
    user_id: uuid.UUID,
    action: AuditLogAction,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[str] = None,
    request: Optional[Request] = None,
):
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    db.add(log)
    db.commit()


def _create_tokens(user_id: uuid.UUID, db: Session) -> dict:
    access = create_access_token(user_id)
    refresh = create_refresh_token(user_id)
    db_refresh = RefreshToken(
        user_id=user_id,
        token=refresh,
        expires_at=datetime.utcnow(),
    )
    db.add(db_refresh)
    db.commit()
    db.refresh(db_refresh)
    return {"access_token": access, "refresh_token": refresh}


# ── Endpoints ─────────────────────────────────────────────────────────


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == body.email, User.deleted_at.is_(None)).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    if db.query(User).filter(User.username == body.username, User.deleted_at.is_(None)).first():
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        email=body.email,
        username=body.username,
        full_name=body.full_name,
    )
    user.set_password(body.password)
    db.add(user)
    db.commit()
    db.refresh(user)

    tokens = _create_tokens(user.id, db)

    _create_audit_log(
        db, user.id, AuditLogAction.USER_CREATED, "user",
        resource_id=str(user.id), request=request,
    )

    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
    }


@router.post("/login", response_model=TokenResponse)
def login(
    body: UserLogin,
    request: Request,
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(
            (User.email == body.login) | (User.username == body.login),
            User.deleted_at.is_(None),
        )
        .first()
    )
    if not user or not user.verify_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    tokens = _create_tokens(user.id, db)

    _create_audit_log(
        db, user.id, AuditLogAction.USER_LOGIN, "user",
        resource_id=str(user.id), request=request,
    )

    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    body: RefreshRequest,
    db: Session = Depends(get_db),
):
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    db_refresh = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token == body.refresh_token,
            RefreshToken.revoked.is_(False),
        )
        .first()
    )
    if not db_refresh or not db_refresh.is_valid():
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

    user = db.query(User).filter(
        User.id == user_id,
        User.deleted_at.is_(None),
        User.is_active.is_(True),
    ).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    new_access = create_access_token(user.id)

    return {
        "access_token": new_access,
        "refresh_token": body.refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout", response_model=MessageResponse)
def logout(
    body: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    db_refresh = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token == body.refresh_token,
            RefreshToken.user_id == current_user.id,
        )
        .first()
    )
    if db_refresh:
        db_refresh.revoked = True
        db_refresh.revoked_at = datetime.utcnow()
        db.commit()

    _create_audit_log(
        db, current_user.id, AuditLogAction.USER_LOGOUT, "user",
        resource_id=str(current_user.id), request=request,
    )

    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def me(
    current_user: User = Depends(get_current_active_user),
):
    return current_user


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not current_user.verify_password(body.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.set_password(body.new_password)
    db.commit()

    # Revoke all refresh tokens for security
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.revoked.is_(False),
    ).update({"revoked": True, "revoked_at": datetime.utcnow()})
    db.commit()

    _create_audit_log(
        db, current_user.id, AuditLogAction.PASSWORD_CHANGED, "user",
        resource_id=str(current_user.id), request=request,
    )

    return {"message": "Password changed successfully"}


@router.get("/api-tokens", response_model=List[APITokenResponse])
def list_api_tokens(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tokens = (
        db.query(APIToken)
        .filter(
            APIToken.user_id == current_user.id,
            APIToken.deleted_at.is_(None),
        )
        .all()
    )
    return tokens


@router.post("/api-tokens", response_model=APITokenCreated, status_code=status.HTTP_201_CREATED)
def create_api_token(
    body: APITokenCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    raw_token = f"stsp_{secrets.token_urlsafe(48)}"
    token_hash = pwd_context.hash(raw_token)

    api_token = APIToken(
        user_id=current_user.id,
        name=body.name,
        token_hash=token_hash,
    )
    db.add(api_token)
    db.commit()
    db.refresh(api_token)

    _create_audit_log(
        db, current_user.id, AuditLogAction.API_TOKEN_CREATED, "api_token",
        resource_id=str(api_token.id), request=None,
    )

    return {
        "id": api_token.id,
        "name": api_token.name,
        "token": raw_token,
        "created_at": api_token.created_at,
    }


@router.delete("/api-tokens/{token_id}", response_model=MessageResponse)
def revoke_api_token(
    token_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    api_token = (
        db.query(APIToken)
        .filter(
            APIToken.id == token_id,
            APIToken.user_id == current_user.id,
            APIToken.deleted_at.is_(None),
        )
        .first()
    )
    if not api_token:
        raise HTTPException(status_code=404, detail="API token not found")

    api_token.deleted_at = datetime.utcnow()
    api_token.is_active = False
    db.commit()

    _create_audit_log(
        db, current_user.id, AuditLogAction.API_TOKEN_REVOKED, "api_token",
        resource_id=str(token_id), request=None,
    )

    return {"message": "API token revoked"}
