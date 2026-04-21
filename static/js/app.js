function initUploadZone(root = document) {
    const dropArea = root.querySelector('.drop-area');
    const fileElem = root.querySelector('#fileElem');

    if (!dropArea || !fileElem || dropArea.dataset.bound === 'true') {
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
}

document.addEventListener('DOMContentLoaded', () => {
    initUploadZone(document);
});

document.body.addEventListener('htmx:load', (evt) => {
    const root = evt.detail && evt.detail.elt ? evt.detail.elt : document;
    initUploadZone(root);
});
