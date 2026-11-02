// FireNOC Management System - Common JavaScript
document.addEventListener('DOMContentLoaded', () => {
    // Enable Bootstrap tooltips if any are present
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
});

