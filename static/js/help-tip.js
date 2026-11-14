/*
 * Help tips: a small «؟» / «i» button next to a setting that explains it in a bubble.
 *
 *   <button type="button" class="xh-help" data-help-tip="متن توضیح" aria-label="راهنمای …">?</button>
 *
 * Opens on hover and on keyboard focus, and on click / tap (a click keeps it open until a second click, Esc, a click
 * elsewhere, or scrolling); one bubble at a time (a single shared element, role="tooltip", linked to the button with
 * aria-describedby). The text is taken as plain text. Works for buttons inside live regions (delegated listeners).
 * The look of the button itself is the page's (e.g. .xh-help in exam-hub.css); the bubble's style is set here.
 */
(() => {
    if (window.__mqHelpTip) return;
    window.__mqHelpTip = true;

    const SEL = '[data-help-tip]';
    const style = document.createElement('style');
    style.textContent = '.mq-help-bubble{position:fixed;z-index:2000;top:0;left:0;max-width:min(19rem,calc(100vw - 16px));padding:.6rem .75rem;'
        + 'border-radius:.6rem;background:#1f2937;color:#fff;font-size:.78rem;font-weight:400;line-height:1.8;text-align:right;direction:rtl;'
        + 'box-shadow:0 10px 24px -8px rgba(15,23,42,.45);white-space:normal;overflow-wrap:anywhere;pointer-events:none}'
        + '.mq-help-bubble[hidden]{display:none}'
        + '[data-help-tip]{cursor:help}';
    document.head.appendChild(style);

    let bubble = null;
    let owner = null;
    let pinned = false;

    const ensureBubble = () => {
        if (bubble && bubble.isConnected) return bubble;
        bubble = document.createElement('div');
        bubble.className = 'mq-help-bubble';
        bubble.id = 'mq-help-bubble';
        bubble.setAttribute('role', 'tooltip');
        bubble.hidden = true;
        document.body.appendChild(bubble);
        return bubble;
    };

    const place = () => {
        if (!owner || !bubble) return;
        // reads first, then one write
        const r = owner.getBoundingClientRect();
        const b = bubble.getBoundingClientRect();
        const vw = document.documentElement.clientWidth;
        const vh = window.innerHeight;
        let top = r.top - b.height - 8;
        if (top < 8) top = Math.min(r.bottom + 8, vh - b.height - 8);
        let left = r.left + r.width / 2 - b.width / 2;
        left = Math.max(8, Math.min(left, vw - b.width - 8));
        bubble.style.transform = `translate(${Math.round(left)}px, ${Math.round(Math.max(8, top))}px)`;
    };

    const open = (button, pin) => {
        const text = (button.getAttribute('data-help-tip') || '').trim();
        if (!text) return;
        if (owner && owner !== button) close();
        ensureBubble();
        owner = button;
        pinned = pin || pinned;
        bubble.textContent = text;
        bubble.style.transform = 'translate(-9999px, 0)';
        bubble.hidden = false;
        button.setAttribute('aria-describedby', bubble.id);
        button.setAttribute('aria-expanded', 'true');
        place();
    };

    const close = () => {
        if (owner) {
            owner.removeAttribute('aria-describedby');
            owner.setAttribute('aria-expanded', 'false');
        }
        owner = null;
        pinned = false;
        if (bubble) bubble.hidden = true;
    };

    document.addEventListener('click', (event) => {
        const button = event.target.closest && event.target.closest(SEL);
        if (button) {
            event.preventDefault();
            if (owner === button && pinned) close();
            else open(button, true);
            return;
        }
        if (owner) close();
    });
    document.addEventListener('pointerover', (event) => {
        if (event.pointerType !== 'mouse') return;
        const button = event.target.closest && event.target.closest(SEL);
        if (button && owner !== button && !pinned) open(button, false);
    });
    document.addEventListener('pointerout', (event) => {
        if (event.pointerType !== 'mouse' || pinned || !owner) return;
        const button = event.target.closest && event.target.closest(SEL);
        if (button === owner && !button.contains(event.relatedTarget) && document.activeElement !== button) close();
    });
    document.addEventListener('focusin', (event) => {
        const button = event.target.closest && event.target.closest(SEL);
        if (button && owner !== button) open(button, false);
    });
    document.addEventListener('focusout', (event) => {
        if (owner && event.target === owner && !pinned) close();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && owner) {
            const button = owner;
            close();
            if (document.activeElement !== button) return;
            event.stopPropagation();
        }
    });
    window.addEventListener('scroll', () => { if (owner) close(); }, {passive: true, capture: true});
    window.addEventListener('resize', () => { if (owner) close(); });
    document.addEventListener('mq:live-load', () => { if (owner && !owner.isConnected) close(); });
})();
