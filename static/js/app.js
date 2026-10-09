/* ---------------------------------------------------------------------------
   Root-scoped scanning helper

   HTMX fires `htmx:load` on each swapped-in element, so the element we are
   handed is frequently the element we are looking for (an uploaded file card,
   for example). `querySelectorAll` only ever returns descendants, which would
   silently skip it — the enhancement would never bind and the UI would sit in
   its loading state until a full page refresh. Always test the root too.
   ------------------------------------------------------------------------- */
function matchWithSelf(root, selector) {
    const found = [];
    if (!root) return found;
    if (typeof root.matches === 'function' && root.matches(selector)) {
        found.push(root);
    }
    if (typeof root.querySelectorAll === 'function') {
        found.push(...root.querySelectorAll(selector));
    }
    return found;
}

function initUploadZone(root = document) {
    const dropAreas = matchWithSelf(root, '.drop-area');
    dropAreas.forEach((dropArea) => {
        if (dropArea.dataset.bound === 'true') {
            return;
        }
        const fileElem = dropArea.querySelector('input[type="file"]');
        if (!fileElem) {
            return;
        }

        dropArea.dataset.bound = 'true';

        // Make the whole drop area clickable
        dropArea.addEventListener('click', (e) => {
            if (e.target.closest('button, label, input, a')) {
                return;
            }
            fileElem.click();
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        function highlight() {
            dropArea.classList.add('is-dragover');
        }

        function unhighlight() {
            dropArea.classList.remove('is-dragover');
        }

        function handleDrop(e) {
            const dt = e.dataTransfer;
            const files = dt && dt.files ? dt.files : null;
            if (!files || files.length === 0) {
                return;
            }

            fileElem.files = files;
            // The form listens to file input changes via htmx hx-trigger.
            fileElem.dispatchEvent(new Event('change', { bubbles: true }));
        }

        // Prevent default drag behaviors
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
            dropArea.addEventListener(eventName, preventDefaults, false);
        });

        // Highlight drop area when item is dragged over it
        ['dragenter', 'dragover'].forEach((eventName) => {
            dropArea.addEventListener(eventName, highlight, false);
        });
        ['dragleave', 'drop'].forEach((eventName) => {
            dropArea.addEventListener(eventName, unhighlight, false);
        });

        // Handle dropped files
        dropArea.addEventListener('drop', handleDrop, false);

        // Allow selecting same file repeatedly and still firing change next time.
        fileElem.addEventListener('click', () => {
            fileElem.value = '';
        });
    });
}

function initMappingHighlights(root = document) {
    const fields = matchWithSelf(root, '.mapping-highlight-field');
    fields.forEach((field) => {
        if (field.dataset.mappingHighlightBound === 'true') {
            return;
        }

        const updateHighlight = () => {
            field.classList.toggle('is-mapped', Boolean(field.value));
        };

        field.dataset.mappingHighlightBound = 'true';
        field.addEventListener('change', updateHighlight);
        field.addEventListener('input', updateHighlight);
        updateHighlight();
    });
}

function initMinAmountFilter(root = document) {
    const inputs = matchWithSelf(root, '.min-amount-filter');
    inputs.forEach((input) => {
        if (input.dataset.amountFilterBound === 'true') {
            return;
        }

        const hint = input.closest('.mapping-row')?.querySelector('.amount-scale-hint');

        function parseAmount(value) {
            const cleaned = value.replace(/,/g, '').replace(/[^\d.]/g, '');
            const firstDot = cleaned.indexOf('.');
            if (firstDot === -1) {
                return cleaned;
            }
            return cleaned.slice(0, firstDot + 1) + cleaned.slice(firstDot + 1).replace(/\./g, '');
        }

        function formatAmount(value) {
            const cleaned = parseAmount(value);
            if (!cleaned) {
                return '';
            }

            const [wholePart, decimalPart] = cleaned.split('.');
            const formattedWhole = wholePart.replace(/^0+(?=\d)/, '').replace(/\B(?=(\d{3})+(?!\d))/g, ',');
            if (cleaned.endsWith('.')) {
                return `${formattedWhole}.`;
            }
            return decimalPart !== undefined ? `${formattedWhole}.${decimalPart}` : formattedWhole;
        }

        function amountScale(value) {
            const amount = Number(parseAmount(value));
            if (!amount) {
                return '';
            }

            const absAmount = Math.abs(amount);
            const scales = [
                { value: 1_000_000_000_000, label: 'trillion or more' },
                { value: 1_000_000_000, label: 'billion' },
                { value: 1_000_000, label: 'million' },
                { value: 1_000, label: 'thousand' },
                { value: 100, label: 'hundred' },
            ];
            const scale = scales.find((item) => absAmount >= item.value);

            if (!scale) {
                return 'Below hundred';
            }

            const scaledAmount = absAmount / scale.value;
            const displayAmount = scaledAmount >= 10
                ? Math.round(scaledAmount).toLocaleString()
                : Number(scaledAmount.toFixed(2)).toLocaleString();
            return `${displayAmount} ${scale.label}`;
        }

        function updateAmount() {
            input.value = formatAmount(input.value);
            if (hint) {
                const scaleText = amountScale(input.value);
                hint.textContent = scaleText ? `Typing: ${input.value} (${scaleText})` : '';
            }
        }

        input.dataset.amountFilterBound = 'true';
        input.addEventListener('input', updateAmount);
        updateAmount();
    });
}

/* ---------------------------------------------------------------------------
   Activity feedback
   ------------------------------------------------------------------------- */

function formatBytes(bytes) {
    if (!bytes) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

function readErrorMessage(event) {
    const xhr = event && event.detail ? event.detail.xhr : null;
    if (!xhr) return 'The request could not be completed. Please try again.';
    if (xhr.status === 413) return 'That file is larger than the allowed upload size.';
    let message = `Request failed (${xhr.status}).`;
    try {
        const data = JSON.parse(xhr.responseText || '');
        if (data && typeof data.detail === 'string') message = data.detail;
    } catch (err) {
        if (xhr.responseText && xhr.responseText.length < 200) message = xhr.responseText;
    }
    return message;
}

function initUploadFeedback(root = document) {
    root && matchWithSelf(root, 'form.js-upload-form').forEach((form) => {
        if (form.dataset.uploadBound === 'true') return;
        form.dataset.uploadBound = 'true';

        const status = form.querySelector('.upload-status');
        const drop = form.querySelector('.drop-area');
        const msg = status ? status.querySelector('[data-role="msg"]') : null;
        const pct = status ? status.querySelector('[data-role="pct"]') : null;
        const bar = status ? status.querySelector('[data-role="bar"]') : null;
        const progress = status ? status.querySelector('[data-role="progress"]') : null;

        const setPhase = (text) => { if (msg) msg.textContent = text; };
        const setBar = (value) => {
            if (bar) bar.style.transform = `scaleX(${Math.max(0, Math.min(100, value)) / 100})`;
            if (progress) progress.setAttribute('aria-valuenow', String(value));
        };

        const start = () => {
            if (status) { status.hidden = false; status.classList.remove('is-error'); }
            if (drop) drop.classList.add('is-busy');
            if (progress) progress.classList.remove('is-indeterminate');
            setBar(0);
            if (pct) pct.textContent = '';
            setPhase('Uploading file…');
        };

        const finish = () => {
            if (status) status.hidden = true;
            if (drop) drop.classList.remove('is-busy');
        };

        const fail = (text) => {
            if (status) { status.hidden = false; status.classList.add('is-error'); }
            if (drop) drop.classList.remove('is-busy');
            setPhase(text);
        };

        form.addEventListener('htmx:beforeRequest', start);

        form.addEventListener('htmx:xhr:progress', (event) => {
            const detail = event.detail || {};
            if (!detail.lengthComputable || !detail.total) return;
            const value = Math.min(100, Math.round((detail.loaded / detail.total) * 100));
            setBar(value);
            if (pct) pct.textContent = `${value}% · ${formatBytes(detail.loaded)} of ${formatBytes(detail.total)}`;
            if (value >= 100) {
                setPhase('Uploaded. Analysing the workbook… large files can take a moment.');
                if (progress) progress.classList.add('is-indeterminate');
                if (pct) pct.textContent = '';
            }
        });

        form.addEventListener('htmx:afterRequest', (event) => {
            if (event.detail && event.detail.successful) finish();
        });

        form.addEventListener('htmx:responseError', (event) => fail(readErrorMessage(event)));
        form.addEventListener('htmx:sendError', () => fail('Upload failed. Check your connection and try again.'));
    });
}

function initProcessingPolling(root = document) {
    // Find all file cards that are in "Processing..." or "Analysing..." state
    const processingCards = matchWithSelf(root, '[data-processing-task]');
    processingCards.forEach((card) => {
        if (card.dataset.pollingBound === 'true') {
            return;
        }
        card.dataset.pollingBound = 'true';

        const taskId = card.dataset.processingTask;
        const fileId = card.dataset.fileId;
        if (!taskId || !fileId) {
            return;
        }

        const msgEl = card.querySelector('[data-role="task-msg-text"]');
        let failures = 0;
        let timer = null;

        const poll = async () => {
            try {
                const auth = window.AKIRSAuth;
                const response = auth
                    ? await auth.apiFetch(`/api/task-status/${taskId}`)
                    : await fetch(`/api/task-status/${taskId}`, {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('akirs_access_token') || ''}` },
                    });
                if (!response.ok) {
                    failures += 1;
                    if (failures >= 5) clearInterval(timer);
                    return;
                }
                failures = 0;
                const task = await response.json();

                if (task.status === 'done' || task.status === 'failed') {
                    clearInterval(timer);
                    // Refresh the file card via htmx
                    if (window.htmx) {
                        window.htmx.trigger(card, 'refreshcard');
                    }
                    return;
                }
                if (msgEl && task.message) msgEl.textContent = task.message;
            } catch (e) {
                failures += 1;
                if (failures >= 5) clearInterval(timer);
            }
        };

        timer = setInterval(poll, 2000);
        poll();
    });
}

function initGlobalActivity() {
    if (window.__activityBound) return;
    window.__activityBound = true;

    let inFlight = 0;
    const bar = document.getElementById('app-progress');
    const sync = () => {
        const busy = inFlight > 0;
        document.body.classList.toggle('is-busy', busy);
        if (bar) bar.hidden = !busy;
    };

    document.body.addEventListener('htmx:beforeRequest', () => { inFlight += 1; sync(); });
    document.body.addEventListener('htmx:afterRequest', () => { inFlight = Math.max(0, inFlight - 1); sync(); });
    document.body.addEventListener('htmx:sendError', () => { inFlight = Math.max(0, inFlight - 1); sync(); });
}

function initGlobalErrors() {
    if (window.__errorsBound) return;
    window.__errorsBound = true;

    const region = document.getElementById('app-alerts');
    if (!region) return;

    const show = (text, kind, sticky) => {
        const el = document.createElement('div');
        el.className = `alert alert-${kind}`;
        el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
        if (kind === 'progress') {
            const spinner = document.createElement('span');
            spinner.className = 'spinner';
            spinner.setAttribute('aria-hidden', 'true');
            el.appendChild(spinner);
        }
        const span = document.createElement('span');
        span.textContent = text;
        el.appendChild(span);
        if (!sticky) {
            const close = document.createElement('button');
            close.type = 'button';
            close.className = 'alert__close';
            close.setAttribute('aria-label', 'Dismiss notification');
            close.textContent = '×';
            close.addEventListener('click', () => el.remove());
            el.appendChild(close);
        }
        region.prepend(el);
        if (!sticky) setTimeout(() => el.remove(), kind === 'error' ? 12000 : 5000);
        return el;
    };

    window.AKIRSNotify = {
        error: (text) => show(text, 'error', false),
        success: (text) => show(text, 'success', false),
        info: (text) => show(text, 'info', false),
        progress: (text) => show(text, 'progress', true),
    };

    document.body.addEventListener('htmx:responseError', (event) => {
        const elt = event.detail ? event.detail.elt : null;
        if (elt && elt.closest && elt.closest('.js-upload-form')) return;
        window.AKIRSNotify.error(readErrorMessage(event));
    });

    document.body.addEventListener('htmx:sendError', () => {
        window.AKIRSNotify.error('Network error. Check your connection and try again.');
    });
}

function initDynamicFormEnhancements(root = document) {
    initUploadZone(root);
    initMappingHighlights(root);
    initMinAmountFilter(root);
    initUploadFeedback(root);
    initProcessingPolling(root);
}

document.addEventListener('DOMContentLoaded', () => {
    initGlobalActivity();
    initGlobalErrors();
    initDynamicFormEnhancements(document);
});

document.body.addEventListener('htmx:load', (evt) => {
    const root = evt.detail && evt.detail.elt ? evt.detail.elt : document;
    initDynamicFormEnhancements(root);
});
