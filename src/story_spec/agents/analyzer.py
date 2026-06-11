"""
Extract structured information about the current state of a web page.
Used by the agentic loop to give the LLM "eyes" into the live DOM.
"""

try:
    from langsmith import traceable
except ImportError:
    def traceable(*args, **kwargs):
        def decorator(fn):
            return fn
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator


@traceable(name="get_page_context", run_type="tool")
async def get_page_context(page) -> dict:
    """Extract all visible interactive elements and text from the current page."""

    context = await page.evaluate("""() => {
        function isVisible(el) {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            return style.display !== 'none'
                && style.visibility !== 'hidden'
                && style.opacity !== '0'
                && el.offsetWidth > 0
                && el.offsetHeight > 0;
        }

        function getUniqueSelector(el) {
            // Try ID first
            if (el.id) return '#' + CSS.escape(el.id);

            // Try data-testid
            const testId = el.getAttribute('data-testid');
            if (testId) return '[data-testid="' + testId + '"]';

            // Try name attribute
            if (el.name) {
                const sel = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                if (document.querySelectorAll(sel).length === 1) return sel;
            }

            // Try type + placeholder combo
            if (el.placeholder) {
                const sel = el.tagName.toLowerCase() + '[placeholder="' + el.placeholder.replace(/"/g, '\\\\"') + '"]';
                if (document.querySelectorAll(sel).length === 1) return sel;
            }

            // Try aria-label
            const ariaLabel = el.getAttribute('aria-label');
            if (ariaLabel) {
                const sel = el.tagName.toLowerCase() + '[aria-label="' + ariaLabel.replace(/"/g, '\\\\"') + '"]';
                if (document.querySelectorAll(sel).length === 1) return sel;
            }

            // Try type attribute for inputs
            if (el.tagName === 'INPUT' && el.type) {
                const sel = 'input[type="' + el.type + '"]';
                if (document.querySelectorAll(sel).length === 1) return sel;
            }

            // Build a path-based selector as fallback
            let path = [];
            let current = el;
            while (current && current !== document.body) {
                let selector = current.tagName.toLowerCase();
                if (current.id) {
                    path.unshift('#' + CSS.escape(current.id));
                    break;
                }
                const parent = current.parentElement;
                if (parent) {
                    const siblings = Array.from(parent.children).filter(s => s.tagName === current.tagName);
                    if (siblings.length > 1) {
                        const index = siblings.indexOf(current) + 1;
                        selector += ':nth-of-type(' + index + ')';
                    }
                }
                path.unshift(selector);
                current = current.parentElement;
            }
            return path.join(' > ');
        }

        function getLabelText(el) {
            // Check for wrapping label
            const parentLabel = el.closest('label');
            if (parentLabel) {
                const clone = parentLabel.cloneNode(true);
                const inputs = clone.querySelectorAll('input, textarea, select');
                inputs.forEach(i => i.remove());
                const text = clone.textContent.trim();
                if (text) return text;
            }
            // Check for associated label via 'for' attribute
            if (el.id) {
                const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                if (label) return label.textContent.trim();
            }
            // Check aria-labelledby
            const labelledBy = el.getAttribute('aria-labelledby');
            if (labelledBy) {
                const label = document.getElementById(labelledBy);
                if (label) return label.textContent.trim();
            }
            return '';
        }

        const result = {
            url: window.location.href,
            title: document.title,
            inputs: [],
            checkables: [],
            buttons: [],
            links: [],
            headings: [],
            visible_text: '',
            forms: []
        };

        // Collect visible input fields
        document.querySelectorAll('input, textarea, select').forEach((el, i) => {
            if (!isVisible(el)) return;
            if (el.type === 'hidden') return;

            if (el.type === 'checkbox' || el.type === 'radio') {
                result.checkables.push({
                    index: i,
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    value: el.value || '',
                    label: getLabelText(el),
                    aria_label: el.getAttribute('aria-label') || '',
                    checked: !!el.checked,
                    required: el.required || false,
                    disabled: el.disabled || false,
                    selector: getUniqueSelector(el)
                });
                return;
            }

            result.inputs.push({
                index: i,
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                placeholder: el.placeholder || '',
                value: el.type === 'password' ? '' : (el.value || ''),
                label: getLabelText(el),
                aria_label: el.getAttribute('aria-label') || '',
                required: el.required || false,
                disabled: el.disabled || false,
                selector: getUniqueSelector(el)
            });
        });

        // Collect visible buttons
        const seenButtons = new Set();
        document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]').forEach((el, i) => {
            if (!isVisible(el)) return;
            const key = el.outerHTML;
            if (seenButtons.has(key)) return;
            seenButtons.add(key);
            result.buttons.push({
                index: i,
                tag: el.tagName.toLowerCase(),
                text: el.textContent.trim().substring(0, 100),
                type: el.type || '',
                id: el.id || '',
                aria_label: el.getAttribute('aria-label') || '',
                disabled: el.disabled || false,
                selector: getUniqueSelector(el)
            });
        });

        // Collect visible links
        document.querySelectorAll('a[href]').forEach((el, i) => {
            if (!isVisible(el)) return;
            const text = el.textContent.trim();
            if (!text) return;
            result.links.push({
                index: i,
                text: text.substring(0, 100),
                href: el.href || '',
                selector: getUniqueSelector(el)
            });
        });

        // Collect headings
        document.querySelectorAll('h1, h2, h3, h4').forEach(el => {
            if (!isVisible(el)) return;
            const text = el.textContent.trim();
            if (text) {
                result.headings.push({
                    tag: el.tagName.toLowerCase(),
                    text: text.substring(0, 200)
                });
            }
        });

        // Collect form info
        document.querySelectorAll('form').forEach((form, i) => {
            result.forms.push({
                index: i,
                action: form.action || '',
                method: form.method || 'get',
                id: form.id || ''
            });
        });

        // Get visible text content (truncated)
        result.visible_text = document.body.innerText.substring(0, 3000);

        return result;
    }""")

    return context




@traceable(name="format_page_context", run_type="tool")
def format_page_context(context: dict) -> str:
    """Format page context into a structured string for the LLM."""

    lines = []
    lines.append(f"URL: {context['url']}")
    lines.append(f"Page Title: {context['title']}")
    lines.append("")

    # Headings
    if context.get('headings'):
        lines.append("HEADINGS:")
        for h in context['headings']:
            lines.append(f"  {h['tag']}: {h['text']}")
        lines.append("")

    # Input fields
    if context.get('inputs'):
        lines.append("INPUT FIELDS:")
        for inp in context['inputs']:
            parts = [f"[INPUT-{inp['index']}]"]
            if inp['tag'] != 'input':
                parts.append(f"tag={inp['tag']}")
            if inp['type']:
                parts.append(f"type={inp['type']}")
            if inp['label']:
                parts.append(f'label="{inp["label"]}"')
            if inp['placeholder']:
                parts.append(f'placeholder="{inp["placeholder"]}"')
            if inp['name']:
                parts.append(f'name="{inp["name"]}"')
            if inp['id']:
                parts.append(f'id="{inp["id"]}"')
            if inp['aria_label']:
                parts.append(f'aria-label="{inp["aria_label"]}"')
            if inp['required']:
                parts.append("REQUIRED")
            if inp['disabled']:
                parts.append("DISABLED")
            if inp['value']:
                parts.append(f'current_value="{inp["value"][:50]}"')
            lines.append(f"  {' | '.join(parts)}")
            lines.append(f"    -> selector: {inp['selector']}")
        lines.append("")

    if context.get('checkables'):
        lines.append("CHECKBOXES / RADIOS:")
        for item in context['checkables']:
            parts = [f"[CHECKABLE-{item['index']}]"]
            if item['type']:
                parts.append(f"type={item['type']}")
            if item['label']:
                parts.append(f'label="{item["label"]}"')
            if item['name']:
                parts.append(f'name="{item["name"]}"')
            if item['id']:
                parts.append(f'id="{item["id"]}"')
            if item['aria_label']:
                parts.append(f'aria-label="{item["aria_label"]}"')
            if item['value']:
                parts.append(f'value="{item["value"]}"')
            parts.append("CHECKED" if item['checked'] else "NOT_CHECKED")
            if item['required']:
                parts.append("REQUIRED")
            if item['disabled']:
                parts.append("DISABLED")
            lines.append(f"  {' | '.join(parts)}")
            lines.append(f"    -> selector: {item['selector']}")
        lines.append("")

    # Buttons
    if context.get('buttons'):
        lines.append("BUTTONS:")
        for btn in context['buttons']:
            parts = [f"[BUTTON-{btn['index']}]"]
            if btn['text']:
                parts.append(f'text="{btn["text"]}"')
            if btn['type']:
                parts.append(f"type={btn['type']}")
            if btn['id']:
                parts.append(f'id="{btn["id"]}"')
            if btn['aria_label']:
                parts.append(f'aria-label="{btn["aria_label"]}"')
            if btn['disabled']:
                parts.append("DISABLED")
            lines.append(f"  {' | '.join(parts)}")
            lines.append(f"    -> selector: {btn['selector']}")
        lines.append("")

    # Links (limit to 20 to avoid token overflow)
    if context.get('links'):
        lines.append("LINKS:")
        for link in context['links'][:20]:
            parts = [f"[LINK-{link['index']}]"]
            parts.append(f'text="{link["text"]}"')
            parts.append(f'href="{link["href"]}"')
            lines.append(f"  {' | '.join(parts)}")
            lines.append(f"    -> selector: {link['selector']}")
        if len(context['links']) > 20:
            lines.append(f"  ... and {len(context['links']) - 20} more links")
        lines.append("")

    # Visible text (truncated)
    if context.get('visible_text'):
        truncated = context['visible_text'][:2000]
        lines.append("VISIBLE TEXT (truncated):")
        lines.append(truncated)
        lines.append("")

    return "\n".join(lines)
