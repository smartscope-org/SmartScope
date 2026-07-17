
function initAdvancedToggle(toggleId, formContainerId) {
  const toggle = document.getElementById(toggleId);
  const container = document.getElementById(formContainerId);
  console.log('toggle:', toggle, 'container:', container);
  
  if (!toggle ) {
    console.warn('initAdvancedToggle: missing toggle, aborting');
    return;
  } 
  if (!container) {
    console.warn('initAdvancedToggle: missing container, aborting');
    return;
  } 

  function applyAdvancedVisibility(showAdvanced) {
    container.querySelectorAll('[data-advanced="true"]').forEach(function (el) {
      el.classList.toggle('d-none', !showAdvanced);
    });
  }

  toggle.addEventListener("change", function () {
    applyAdvancedVisibility(this.checked);
  });

  applyAdvancedVisibility(toggle.checked);

  if (container.querySelector('[data-advanced="true"] .is-invalid')) {
    toggle.checked = true;
    applyAdvancedVisibility(true);
  }
}

const ADVANCED_TOGGLES = [
    { toggleId: 'advancedToggleColParams', targetId: 'formParams', containerId: 'formParams' },
    { toggleId: 'advancedToggleColParamsEdit', targetId: 'editCollectionParamsForm', containerId: 'formParamsEdit' },
];

// Re-run after any htmx swap, matching whichever container was actually swapped
document.body.addEventListener('htmx:afterSwap', function (evt) {
    ADVANCED_TOGGLES.forEach(({ toggleId, targetId, containerId }) => {
        if (evt.detail.target.id === targetId) {
            initAdvancedToggle(toggleId, containerId);
        }
    });
});