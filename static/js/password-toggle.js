/* Show/hide («چشم») button on every password input, as on most sites: an eye at the end of the field (left in RTL),
   click to show the typed text, click again to hide. It never reveals a stored password, since none is ever sent to the
   page. Inputs added later (live regions, dialogs, script-built forms) get it too through a MutationObserver, which runs
   before the next paint, so nothing jumps. Skip an input with data-no-password-toggle. Loaded by base.html,
   base_standalone.html, login.html and register.html. */
(function () {
  var EYE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18M10.6 5.6A9.7 9.7 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-3 3.7M6.6 6.6A16.6 16.6 0 0 0 2.5 12S6 18.5 12 18.5a9.3 9.3 0 0 0 4.4-1.1M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';

  function addStyle() {
    if (document.getElementById('pw-toggle-style')) return;
    var style = document.createElement('style');
    style.id = 'pw-toggle-style';
    // The wrapper is a <span> (valid inside <label>); pages style "label span" / ".x-field span" as caption text,
    // so its box is reset here.
    style.textContent = '.pw-toggle-wrap.pw-toggle-wrap{position:relative;display:block;flex:1 1 auto;min-width:0;width:100%;max-width:100%;margin:0!important;padding:0!important;border:0!important;border-radius:0!important;background:none!important;box-shadow:none!important;height:auto!important;line-height:normal;white-space:normal}'
      + '.pw-toggle-wrap>input{width:100%!important;max-width:100%;box-sizing:border-box;padding-left:2.75rem!important}'
      // Edge/IE draw their own reveal eye: hide it so there is only one.
      + '.pw-toggle-wrap>input::-ms-reveal,.pw-toggle-wrap>input::-ms-clear{display:none}'
      // Doubled classes: pages style "label svg" / "label button" (e.g. register's field icons are absolute).
      + '.pw-toggle-btn.pw-toggle-btn{position:absolute;left:.3rem;right:auto;top:50%;bottom:auto;transform:translateY(-50%);display:inline-grid;place-items:center;width:2.1rem;height:2.1rem;min-width:0;min-height:0;margin:0;padding:0;border:0;border-radius:.5rem;background:transparent;color:var(--pw-c,#64748b);opacity:.85;cursor:pointer;box-shadow:none;line-height:1;transition:opacity .15s,background-color .15s}'
      // A browser-filled (autofill) field gets the browser's light background and dark text whatever the page says,
      // which made the eye light-on-light on the dark login card: give it a dark colour then. Separate rules,
      // since a browser drops a whole selector list with a pseudo-class it doesn't know.
      + '.pw-toggle-wrap>input:-webkit-autofill+.pw-toggle-btn.pw-toggle-btn{color:#334155;opacity:1}'
      + '.pw-toggle-wrap>input:autofill+.pw-toggle-btn.pw-toggle-btn{color:#334155;opacity:1}'
      + '.pw-toggle-btn.pw-toggle-btn:hover{opacity:1;background:color-mix(in srgb,currentColor 12%,transparent)}'
      + '.pw-toggle-btn.pw-toggle-btn:focus-visible{opacity:1;outline:2px solid currentColor;outline-offset:1px}'
      + '.pw-toggle-btn.pw-toggle-btn[aria-pressed="true"]{opacity:1}'
      + '.pw-toggle-btn.pw-toggle-btn:disabled{opacity:.35;cursor:default;background:transparent}'
      + '.pw-toggle-btn.pw-toggle-btn svg{position:static;inset:auto;transform:none;margin:0;display:block;width:1.15rem;height:1.15rem;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;pointer-events:none;color:inherit;opacity:1}';
    document.head.appendChild(style);
  }

  function setShown(input, button, show) {
    input.type = show ? 'text' : 'password';
    button.innerHTML = show ? EYE_OFF : EYE;
    button.setAttribute('aria-pressed', show ? 'true' : 'false');
    button.setAttribute('aria-label', show ? 'پنهان کردن رمز عبور' : 'نمایش رمز عبور');
    button.title = show ? 'پنهان کردن رمز عبور' : 'نمایش رمز عبور';
  }

  function enhance(input) {
    if (input.dataset.pwToggle || input.hasAttribute('data-no-password-toggle') || !input.parentNode) return;
    input.dataset.pwToggle = '1';
    var wrap = document.createElement('span');
    wrap.className = 'pw-toggle-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'pw-toggle-btn';
    button.setAttribute('data-no-loader', '');
    button.setAttribute('aria-controls', input.id || '');
    if (!input.id) button.removeAttribute('aria-controls');
    button.disabled = input.disabled;
    setShown(input, button, false);
    // Keep the caret in the field (no focus jump) when clicked with the mouse.
    button.addEventListener('mousedown', function (e) { e.preventDefault(); });
    button.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation(); // the field usually sits in a <label>: don't let the click re-trigger it
      setShown(input, button, input.type === 'password');
    });
    // Hide again before the form is sent, so the browser never stores it as a plain text field.
    if (input.form) input.form.addEventListener('submit', function () { setShown(input, button, false); });
    // Follow the field's disabled state (e.g. «تعیین رمز جدید» fields enabled by a switch).
    if (window.MutationObserver) {
      new MutationObserver(function () { button.disabled = input.disabled; })
        .observe(input, { attributes: true, attributeFilter: ['disabled'] });
    }
    wrap.appendChild(button);
    // Eye in the field's own text colour, so it reads on light and dark fields alike.
    // Re-read it when the field is used (theme switched live, error/focus styles), never on a timer.
    function syncColor() {
      var color = getComputedStyle(input).color;
      if (color && wrap.style.getPropertyValue('--pw-c') !== color) wrap.style.setProperty('--pw-c', color);
    }
    syncColor();
    wrap.addEventListener('pointerenter', syncColor);
    wrap.addEventListener('focusin', syncColor);
    input.addEventListener('input', syncColor);
  }

  function scan(root) {
    var inputs = root.querySelectorAll ? root.querySelectorAll('input[type="password"]') : [];
    if (root.matches && root.matches('input[type="password"]')) inputs = [root];
    if (!inputs.length) return;
    addStyle();
    Array.prototype.forEach.call(inputs, enhance);
  }

  function run() {
    scan(document);
    if (!window.MutationObserver || !document.body) return;
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var added = records[i].addedNodes;
        for (var j = 0; j < added.length; j++) if (added[j].nodeType === 1) scan(added[j]);
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
})();
