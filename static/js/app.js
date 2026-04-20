document.addEventListener('DOMContentLoaded', () => {
    const dropArea = document.querySelector('.drop-area');
    const fileElem = document.getElementById('fileElem');
    const uploadForm = document.getElementById('upload-form');

    // Make the whole drop area clickable
    dropArea.addEventListener('click', () => {
        fileElem.click();
    });

    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // Highlight drop area when item is dragged over it
    ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, unhighlight, false);
    });

    function highlight(e) {
        dropArea.style.borderColor = 'var(--primary)';
        dropArea.style.background = 'rgba(59, 130, 246, 0.1)';
    }

    function unhighlight(e) {
        dropArea.style.borderColor = 'var(--glass-border)';
        dropArea.style.background = 'var(--glass-bg)';
    }

    // Handle dropped files
    dropArea.addEventListener('drop', handleDrop, false);

    function handleDrop(e) {
        let dt = e.dataTransfer;
        let files = dt.files;

        fileElem.files = files; // Assign files to input
        htmx.trigger(uploadForm, 'submit'); // Trigger htmx upload
    }
});
