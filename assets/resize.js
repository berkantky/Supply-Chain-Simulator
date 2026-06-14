// Trigger Plotly resize when switching tabs so charts fill their container
document.addEventListener('DOMContentLoaded', function () {
    const observer = new MutationObserver(function () {
        window.dispatchEvent(new Event('resize'));
    });
    observer.observe(document.body, {
        subtree: true,
        attributes: true,
        attributeFilter: ['class']
    });
});
