const API = '';   // same origin

let currentPage = 'dashboard';
let liveRunId   = null;
let liveStream  = null;
let liveStepCount = 0;

function navigate(page, data = {}) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) pageEl.classList.add('active');

  const navEl = document.getElementById(`nav-${page}`) || document.querySelector(`[data-page="${page}"]`);
  if (navEl) navEl.classList.add('active');

  currentPage = page;

  if (page === 'dashboard')   loadDashboard();
  if (page === 'history')     loadHistory();
  if (page === 'run-detail')  loadRunDetail(data.runId);
  if (page === 'live')        renderLivePage();
}

document.querySelectorAll('[data-page]').forEach(el => {
  el.addEventListener('click', e => {
    e.preventDefault();
    navigate(el.dataset.page);
  });
});

function setGreeting() {
  const hour = new Date().getHours();
  const g = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const el = document.getElementById('dashboard-greeting');
  if (el) el.textContent = `${g}, Curator.`;
}

async function loadDashboard() {
  setGreeting();
  try {
    const runs = await apiGet('/api/runs');
    renderStats(runs);
    renderDashboardRuns(runs.slice(0, 5));
  } catch (err) {
    document.getElementById('dashboard-runs').innerHTML = errorHtml(err);
  }
}

function renderStats(runs) {
  const total = runs.length;
  const passed = runs.filter(r => r.overall_status === 'pass').length;
  const rate   = total ? Math.round((passed / total) * 100) : 0;
  const avgMs  = total
    ? Math.round(runs.reduce((s, r) => s + (r.total_duration_ms || 0), 0) / total)
    : 0;
  const dayAgo = Date.now() / 1000 - 86400;
  const last24 = runs.filter(r => r.created_at > dayAgo).length;

  setText('stat-total',   total  || '0');
  setText('stat-success', total  ? `${rate}%` : '—');
  setText('stat-avg',     total  ? fmtMs(avgMs) : '—');
  setText('stat-24h',     last24 || '0');
}

function renderDashboardRuns(runs) {
  const el = document.getElementById('dashboard-runs');
  if (!runs.length) {
    el.innerHTML = emptyHtml('No sequences yet.', 'Run your first test to get started.', 'add_circle');
    return;
  }
  el.innerHTML = runs.map(runCard).join('');
  el.querySelectorAll('.run-card').forEach(card => {
    card.addEventListener('click', () => navigate('run-detail', { runId: card.dataset.runId }));
  });
}

let _allRuns = [];

async function loadHistory() {
  try {
    _allRuns = await apiGet('/api/runs');
    renderHistoryList(_allRuns);
  } catch (err) {
    document.getElementById('history-list').innerHTML = errorHtml(err);
  }
}

function renderHistoryList(runs) {
  const el = document.getElementById('history-list');
  if (!runs.length) {
    el.innerHTML = emptyHtml('No history yet.', 'Completed test runs will appear here.', 'history');
    return;
  }
  el.innerHTML = runs.map(runCard).join('');
  el.querySelectorAll('.run-card').forEach(card => {
    card.addEventListener('click', () => navigate('run-detail', { runId: card.dataset.runId }));
  });
}

document.getElementById('history-search').addEventListener('input', e => {
  const q = e.target.value.toLowerCase();
  const filtered = _allRuns.filter(r =>
    r.story.toLowerCase().includes(q) ||
    r.url.toLowerCase().includes(q) ||
    r.id.toLowerCase().includes(q)
  );
  renderHistoryList(filtered);
});

function runCard(run) {
  const st = run.overall_status;
  const ago = timeAgo(run.created_at);
  const dur = fmtMs(run.total_duration_ms);
  const steps = run.steps ? run.steps.length : '?';

  return `
    <div class="run-card ${st}" data-run-id="${run.id}">
      <span class="run-status-dot ${st}"></span>
      <div class="run-info">
        <div class="run-story">${escHtml(run.story)}</div>
        <div class="run-meta">
          <span class="run-meta-item">
            <span class="material-icons-round">schedule</span>${ago}
          </span>
          <span class="run-meta-item">
            <span class="material-icons-round">link</span>${escHtml(run.url)}
          </span>
          <span class="run-meta-item">
            <span class="material-icons-round">timer</span>${dur}
          </span>
          <span class="run-meta-item">
            <span class="material-icons-round">checklist</span>${run.passed}p / ${run.failed}f
          </span>
        </div>
      </div>
      <div class="run-chips">
        <span class="chip ${st}">${st.toUpperCase()}</span>
      </div>
      <span class="run-id">#${run.id}</span>
    </div>`;
}

async function loadRunDetail(runId) {
  if (!runId) return;
  // Clear
  setText('detail-title', 'Loading…');
  setText('detail-subtitle', '');
  setText('detail-summary', '');
  document.getElementById('detail-meta').innerHTML = '';
  document.getElementById('detail-log').innerHTML  = '<div class="skeleton" style="height:80px"></div>';
  document.getElementById('detail-verdict-badge').textContent = '';
  document.getElementById('detail-verdict-badge').className   = 'verdict-badge';

  try {
    const run = await apiGet(`/api/runs/${runId}`);
    renderRunDetail(run);
  } catch (err) {
    setText('detail-title', 'Error loading run');
    setText('detail-subtitle', String(err));
  }
}

function renderRunDetail(run) {
  const st = run.overall_status;

  setText('detail-title', run.story.length > 60 ? run.story.slice(0, 60) + '…' : run.story);
  setText('detail-subtitle', `Run #${run.id}  ·  ${timeAgo(run.created_at)}`);

  const badge = document.getElementById('detail-verdict-badge');
  badge.textContent = st.toUpperCase();
  badge.className   = `verdict-badge ${st}`;

  // Meta row
  document.getElementById('detail-meta').innerHTML = `
    <span class="meta-tag"><span class="material-icons-round">link</span>${escHtml(run.url)}</span>
    <span class="meta-tag"><span class="material-icons-round">timer</span>${fmtMs(run.total_duration_ms)}</span>
    <span class="meta-tag"><span class="material-icons-round">checklist</span>${run.passed} passed / ${run.failed} failed</span>
    <span class="meta-tag"><span class="material-icons-round">tag</span>#${run.id}</span>
  `;

  // Summary
  const summaryBlock = document.getElementById('detail-summary-block');
  const summaryEl    = document.getElementById('detail-summary');
  if (run.summary) {
    summaryEl.textContent = run.summary;
    summaryBlock.classList.remove('hidden');
  } else {
    summaryBlock.classList.add('hidden');
  }

  // Step count
  setText('detail-step-count', `${run.steps.length} steps`);

  // Steps
  const log = document.getElementById('detail-log');
  if (!run.steps.length) {
    log.innerHTML = emptyHtml('No steps recorded.', '', 'list');
    return;
  }

  log.innerHTML = run.steps.map((step, i) => {
    const statusIcon = step.status === 'pass' ? 'check_circle' : step.status === 'fail' ? 'cancel' : 'radio_button_unchecked';

    // screenshot src
    const ssrc = step.screenshot
      ? `/screenshot/${run.id}/${step.screenshot}`
      : null;

    return `
      <div class="exec-step" id="step-${i}">
        <div class="exec-step-header" onclick="toggleStep(${i})">
          <span class="step-num">${String(step.index + 1).padStart(2,'0')}</span>
          <span class="step-action-badge">${escHtml(step.action)}</span>
          <span class="step-desc">${escHtml(step.description)}</span>
          <span class="material-icons-round step-status-icon ${step.status}">${statusIcon}</span>
          <span class="step-dur">${fmtMs(step.duration_ms)}</span>
        </div>
        <div class="exec-step-body">
          ${step.error ? `<div class="step-error-box">${escHtml(step.error)}</div>` : ''}
          ${step.target ? `<div style="font-size:.75rem;color:var(--text-muted);font-family:'JetBrains Mono',monospace;">target: ${escHtml(step.target)}</div>` : ''}
          ${step.value  ? `<div style="font-size:.75rem;color:var(--text-muted);font-family:'JetBrains Mono',monospace;">value: ${escHtml(step.value)}</div>` : ''}
          ${ssrc ? `<div class="step-screenshot"><img src="${ssrc}" alt="Screenshot step ${step.index + 1}" loading="lazy" /></div>` : ''}
        </div>
      </div>`;
  }).join('');
}

window.toggleStep = function(i) {
  document.getElementById(`step-${i}`).classList.toggle('open');
};

document.getElementById('btn-new-test-shortcut').addEventListener('click', () => navigate('new-test'));
document.getElementById('btn-cancel-test').addEventListener('click', () => navigate('dashboard'));

document.getElementById('btn-run-test').addEventListener('click', async () => {
  const url      = document.getElementById('input-url').value.trim();
  const story    = document.getElementById('input-story').value.trim();
  const headless = document.getElementById('input-headless').checked;
  const errBox   = document.getElementById('form-error');
  const errMsg   = document.getElementById('form-error-msg');

  errBox.classList.add('hidden');

  if (!url) return showFormError('Please enter a target URL.');
  if (!story) return showFormError('Please describe the user story.');

  try {
    new URL(url);
  } catch {
    return showFormError('Please enter a valid URL (include https://).');
  }

  const btn = document.getElementById('btn-run-test');
  btn.disabled = true;
  btn.innerHTML = '<span class="material-icons-round" style="animation:spin 1s linear infinite">autorenew</span> Initiating…';

  try {
    const { run_id } = await apiPost('/api/runs', { url, story, headless });
    liveRunId = run_id;
    liveStepCount = 0;
    resetLivePage(url, story, run_id);
    navigate('live');
    startLiveStream(run_id);
  } catch (err) {
    showFormError(String(err));
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="material-icons-round">play_arrow</span> Initiate Sequence';
  }
});

function showFormError(msg) {
  document.getElementById('form-error-msg').textContent = msg;
  document.getElementById('form-error').classList.remove('hidden');
}

function resetLivePage(url, story, runId) {
  setLiveStatus('running', 'Running');
  setText('live-subtitle', `Active run #${runId}`);

  setText('live-url', url);
  setText('live-story', story.length > 80 ? story.slice(0,80)+'…' : story);
  document.getElementById('live-meta').classList.remove('hidden');
  document.getElementById('live-progress-wrap').classList.remove('hidden');
  setProgress(0, 25);

  const log = document.getElementById('live-log');
  log.innerHTML = '';
  document.getElementById('live-log-empty').style.display = 'none';
  document.getElementById('live-result').classList.add('hidden');

  document.getElementById('live-badge').classList.remove('hidden');

  setAgentStatus('running', 'Agent Running');
}

function renderLivePage() {
  if (!liveRunId) {
    setLiveStatus('idle', 'Idle');
    setText('live-subtitle', 'No active run.');
    document.getElementById('live-meta').classList.add('hidden');
    document.getElementById('live-progress-wrap').classList.add('hidden');
    document.getElementById('live-result').classList.add('hidden');
  }
}

function setLiveStatus(state, text) {
  const pill = document.getElementById('live-status-pill');
  pill.innerHTML = `<span class="dot ${state}"></span><span id="live-status-text">${text}</span>`;
}

function setProgress(done, total) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  document.getElementById('live-progress-fill').style.width = `${pct}%`;
  document.getElementById('live-progress-label').textContent = `${done} / ${total} steps`;
}

function startLiveStream(runId) {
  if (liveStream) { liveStream.close(); liveStream = null; }

  liveStream = new EventSource(`/api/runs/${runId}/stream`);
  const log = document.getElementById('live-log');

  liveStream.onmessage = ev => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }

    if (data.type === 'step') {
      liveStepCount++;
      setProgress(liveStepCount, 25);
      appendLogEntry(log, data);
    }

    if (data.type === 'finished') {
      liveStream.close();
      liveStream = null;
      finishLiveRun(data, runId);
    }

    if (data.type === 'error') {
      liveStream.close();
      liveStream = null;
      appendLogEntry(log, { action: 'error', description: data.message, status: 'fail' });
      setLiveStatus('fail', 'Error');
      setAgentStatus('idle', 'Agent Idle');
      document.getElementById('live-badge').classList.add('hidden');
    }

    if (data.type === 'done') {
      liveStream.close();
      liveStream = null;
    }

    log.scrollTop = log.scrollHeight;
  };

  liveStream.onerror = () => {
    liveStream.close();
    liveStream = null;
    setLiveStatus('idle', 'Disconnected');
    setAgentStatus('idle', 'Agent Idle');
    document.getElementById('live-badge').classList.add('hidden');
  };
}

function appendLogEntry(log, step) {
  const icon = step.status === 'pass' ? 'check_circle' : step.status === 'fail' ? 'cancel' : 'autorenew';
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `
    <span class="material-icons-round log-icon ${step.status}">${icon}</span>
    <div class="log-body">
      <div class="log-action">${escHtml(step.action || '')}</div>
      <div class="log-desc">${escHtml(step.description || '')}</div>
      ${step.error ? `<div class="log-error">${escHtml(step.error)}</div>` : ''}
    </div>
    ${step.duration_ms ? `<span class="log-dur">${fmtMs(step.duration_ms)}</span>` : ''}
  `;
  log.appendChild(entry);
}

function finishLiveRun(data, runId) {
  setLiveStatus(data.overall_status, data.overall_status === 'pass' ? 'Passed' : 'Failed');
  setAgentStatus('idle', 'Agent Idle');
  document.getElementById('live-badge').classList.add('hidden');
  setProgress(liveStepCount, liveStepCount);

  const result = document.getElementById('live-result');
  result.classList.remove('hidden');

  document.getElementById('live-verdict').textContent =
    data.overall_status === 'pass' ? '✓ Goal Achieved' : '✗ Goal Not Achieved';
  document.getElementById('live-verdict').className =
    `result-verdict ${data.overall_status}`;

  document.getElementById('live-result-stats').innerHTML = `
    <div class="result-stat">
      <span class="result-stat-label">Steps Passed</span>
      <span class="result-stat-val">${data.passed}</span>
    </div>
    <div class="result-stat">
      <span class="result-stat-label">Steps Failed</span>
      <span class="result-stat-val">${data.failed}</span>
    </div>
    <div class="result-stat">
      <span class="result-stat-label">Duration</span>
      <span class="result-stat-val">${fmtMs(data.total_duration_ms)}</span>
    </div>
  `;

  if (data.summary) {
    document.getElementById('live-summary').textContent = data.summary;
    document.getElementById('live-summary').style.display = 'block';
  } else {
    document.getElementById('live-summary').style.display = 'none';
  }

  document.getElementById('btn-view-details').onclick = () => {
    navigate('run-detail', { runId });
  };
  document.getElementById('btn-new-from-result').onclick = () => {
    liveRunId = null;
    navigate('new-test');
  };

  liveRunId = null;
}

function setAgentStatus(state, text) {
  const el = document.getElementById('agent-status');
  el.innerHTML = `<span class="dot ${state}"></span><span id="agent-status-text">${text}</span>`;
}

document.getElementById('btn-back').addEventListener('click', () => navigate('history'));
document.getElementById('view-all-link').addEventListener('click', e => { e.preventDefault(); navigate('history'); });

const spinStyle = document.createElement('style');
spinStyle.textContent = '@keyframes spin { to { transform: rotate(360deg); } }';
document.head.appendChild(spinStyle);

async function apiGet(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function escHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtMs(ms) {
  if (!ms && ms !== 0) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms/1000).toFixed(1)}s`;
  return `${Math.floor(ms/60000)}m ${Math.round((ms%60000)/1000)}s`;
}

function timeAgo(ts) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff/60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff/3600)} hour${Math.floor(diff/3600)>1?'s':''} ago`;
  return `${Math.floor(diff/86400)} day${Math.floor(diff/86400)>1?'s':''} ago`;
}

function emptyHtml(title, sub = '', icon = 'inbox') {
  return `<div class="empty-state">
    <span class="material-icons-round">${icon}</span>
    <p><strong>${title}</strong>${sub ? `<br/>${sub}` : ''}</p>
  </div>`;
}

function errorHtml(err) {
  return `<div class="empty-state">
    <span class="material-icons-round">error_outline</span>
    <p><strong>Failed to load data</strong><br/>${escHtml(String(err))}</p>
  </div>`;
}

navigate('dashboard');
