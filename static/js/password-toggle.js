/* Show/hide button on password inputs: lets a user check what they are typing. It never reveals a stored password,
   since none is ever sent to the page. Skips inputs marked data-no-password-toggle. */
(function () {
  var EYE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18M10.6 5.6A9.7 9.7 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-3 3.7M6.6 6.6A16.6 16.6 0 0 0 2.5 12S6 18.5 12 18.5a9.3 9.3 0 0 0 4.4-1.1M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';

  function addStyle() {
    if (document.getElementById('pw-toggle-style')) return;
    var style = document.createElement('style');
    style.id = 'pw-toggle-style';
    style.textContent = '.pw-toggle-wrap{position:relative;display:block;flex:1 1 auto;min-width:0;width:100%}'
      + '.pw-toggle-wrap>input{width:100%;padding-left:2.6rem!important}'
      + '.pw-toggle-btn{position:absolute;left:.35rem;top:50%;transform:translateY(-50%);display:inline-grid;place-items:center;width:2rem;height:2rem;padding:0;border:0;border-radius:.45rem;background:transparent;color:#64748b;cursor:pointer}'
      + '.pw-toggle-btn:hover,.pw-toggle-btn:focus-visible{background:rgba(37,99,235,.08);color:#2563eb}'
      + '.pw-toggle-btn svg{width:1.15rem;height:1.15rem;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}';
    document.head.appendChild(style);
  }

  function enhance(input) {
    if (input.dataset.pwToggle || input.hasAttribute('data-no-password-toggle')) return;
    input.dataset.pwToggle = '1';
    var wrap = document.createElement('span');
    wrap.className = 'pw-toggle-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'pw-toggle-btn';
    button.setAttribute('aria-label', 'نمایش رمز');
    button.innerHTML = EYE;
    button.addEventListener('click', function () {
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.innerHTML = show ? EYE_OFF : EYE;
      button.setAttribute('aria-label', show ? 'پنهان کردن رمز' : 'نمایش رمز');
    });
    // Hide again before the form is sent, so the browser never stores it as a plain text field.
    if (input.form) input.form.addEventListener('submit', function () { input.type = 'password'; });
    wrap.appendChild(button);
  }

  function run() {
    var inputs = document.querySelectorAll('input[type="password"]');
    if (!inputs.length) return;
    addStyle();
    inputs.forEach(enhance);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
})();
