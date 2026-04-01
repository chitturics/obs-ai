/**
 * Chainlit prefill script — reads ?msg= URL parameter and auto-fills
 * the chat input.  Loaded via custom_js in .chainlit/config.toml.
 */
(function () {
  var params = new URLSearchParams(window.location.search);
  var msg = params.get('msg');
  if (!msg) return;

  // Clean the URL so a page refresh doesn't re-fill
  var clean = window.location.pathname + window.location.hash;
  window.history.replaceState(null, '', clean);

  // Wait for the Chainlit textarea to appear (React renders async)
  var attempts = 0;
  var maxAttempts = 50; // 5 seconds max

  function tryFill() {
    attempts++;
    var textarea = document.querySelector('textarea[placeholder]');
    if (!textarea) {
      if (attempts < maxAttempts) {
        setTimeout(tryFill, 100);
      }
      return;
    }

    // React-compatible value setter: bypass React's synthetic state
    var nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value'
    ).set;
    nativeSetter.call(textarea, msg);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    textarea.focus();
  }

  // Start polling after a short delay for Chainlit to initialise
  setTimeout(tryFill, 300);
})();
