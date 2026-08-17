function initUploadZone(root = document) {
    const dropAreas = root.querySelectorAll('.drop-area');
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
            dropArea.style.borderColor = 'var(--primary)';
            dropArea.style.background = 'rgba(59, 130, 246, 0.1)';
        }

        function unhighlight() {
            dropArea.style.borderColor = 'var(--glass-border)';
            dropArea.style.background = 'var(--glass-bg)';
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
    const fields = root.querySelectorAll('.mapping-highlight-field');
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
    const inputs = root.querySelectorAll('.min-amount-filter');
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

function initDynamicFormEnhancements(root = document) {
    initUploadZone(root);
    initMappingHighlights(root);
    initMinAmountFilter(root);
}

document.addEventListener('DOMContentLoaded', () => {
    initDynamicFormEnhancements(document);
});

document.body.addEventListener('htmx:load', (evt) => {
    const root = evt.detail && evt.detail.elt ? evt.detail.elt : document;
    initDynamicFormEnhancements(root);
});
