/* Multi-select dropdown of question types; markup and styles in static/css/type-multiselect.css.
   Ticking a type updates the summary text and fires a bubbling "mq:type-ms-change" event
   (event.detail.keys = Set of picked values) on the <details>. Inside a form the checkboxes
   submit as repeated name=value pairs. All listeners are delegated, so it also works in live regions.
   data-submit-on-close (filter forms): when the dropdown closes with a different pick than it opened with, its form
   is submitted (requestSubmit, so live regions apply it without a reload); ticking several types stays one request. */
(() => {
    const ALL = 'همه انواع سؤال';
    const fa = (n) => String(n).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
    const sync = (ms) => {
        const picked = [...ms.querySelectorAll('[data-type-option]:checked')];
        ms.classList.toggle('has-value', picked.length > 0);
        const text = ms.querySelector('[data-type-ms-text]');
        if (text) {
            text.textContent = !picked.length ? ALL
                : picked.length === 1 ? (picked[0].closest('label').querySelector('.type-ms-label') || picked[0].closest('label')).textContent.trim()
                : `${fa(picked.length)} نوع سؤال`;
        }
        ms.dispatchEvent(new CustomEvent('mq:type-ms-change', {bubbles: true, detail: {keys: new Set(picked.map((o) => o.value))}}));
    };
    const picks = (ms) => [...ms.querySelectorAll('[data-type-option]:checked')].map((o) => o.value).join(',');
    document.addEventListener('toggle', (event) => {  // <details> toggle does not bubble: listen in the capture phase
        const ms = event.target;
        if (!ms.matches || !ms.matches('[data-type-ms][data-submit-on-close]')) return;
        if (ms.open) { ms.dataset.openPicks = picks(ms); return; }
        const before = ms.dataset.openPicks;
        delete ms.dataset.openPicks;
        const form = ms.closest('form');
        if (before !== undefined && before !== picks(ms) && form) form.requestSubmit();
    }, true);
    document.addEventListener('change', (event) => {
        const ms = event.target.closest && event.target.matches('[data-type-option]') && event.target.closest('[data-type-ms]');
        if (ms) sync(ms);
    });
    document.addEventListener('click', (event) => {
        const clear = event.target.closest('[data-type-ms-clear]');
        if (clear) {
            const ms = clear.closest('[data-type-ms]');
            ms.querySelectorAll('[data-type-option]').forEach((o) => { o.checked = false; });
            sync(ms);
            ms.open = false;
            return;
        }
        document.querySelectorAll('[data-type-ms][open]').forEach((ms) => { if (!ms.contains(event.target)) ms.open = false; });
    });
    /* Opening: ancestors that form their own stacking context (backdrop-filter "glass" cards, transforms…)
       would trap the panel's z-index under later cards, so they're lifted while it is open. The panel opens
       upwards when there's clearly more room above, and its height is capped to the room it has. */
    const makesContext = (cs) => cs.backdropFilter !== 'none' && cs.backdropFilter !== undefined
        || (cs.webkitBackdropFilter && cs.webkitBackdropFilter !== 'none')
        || cs.filter !== 'none' || cs.transform !== 'none' || Number(cs.opacity) < 1
        || cs.isolation === 'isolate' || (cs.zIndex !== 'auto' && cs.position !== 'static');
    const lifted = new Map();
    const lift = (ms) => {
        const list = [];
        for (let el = ms.parentElement; el && el !== document.body; el = el.parentElement) {
            const cs = getComputedStyle(el);
            if (!makesContext(cs)) continue;
            list.push([el, el.style.zIndex, el.style.position]);
            if (cs.position === 'static') el.style.position = 'relative';
            el.style.zIndex = '60';
        }
        lifted.set(ms, list);
    };
    const drop = (ms) => {
        (lifted.get(ms) || []).forEach(([el, z, pos]) => { el.style.zIndex = z; el.style.position = pos; });
        lifted.delete(ms);
    };
    const place = (ms) => {
        const panel = ms.querySelector('.type-ms-panel');
        if (!panel) return;
        ms.classList.remove('is-up');
        panel.style.maxHeight = '';
        const box = ms.querySelector('summary').getBoundingClientRect();
        const want = Math.min(panel.scrollHeight + 2, 21 * 16);
        // visible area = the nearest scrolling ancestor (pages scroll inside a box under a fixed header), else the window
        let top = 0, bottom = window.innerHeight;
        for (let el = ms.parentElement; el && el !== document.body; el = el.parentElement) {
            if (!/(auto|scroll|hidden)/.test(getComputedStyle(el).overflowY)) continue;
            const r = el.getBoundingClientRect();
            top = Math.max(top, r.top); bottom = Math.min(bottom, r.bottom);
            break;
        }
        // skip fixed/sticky bars (site header) covering the top of that area
        const x = (box.left + box.right) / 2;
        for (let guard = 0; guard < 5 && top < box.top; guard += 1) {
            let el = document.elementFromPoint(x, top + 1);
            while (el && el !== document.body && !/fixed|sticky/.test(getComputedStyle(el).position)) el = el.parentElement;
            if (!el || el === document.body || el.contains(ms)) break;
            top = Math.max(top + 1, el.getBoundingClientRect().bottom);
        }
        const below = bottom - box.bottom - 12;
        const above = box.top - top - 12;
        const up = below < want && above > below;
        ms.classList.toggle('is-up', up);
        panel.style.maxHeight = `${Math.max(160, Math.min(want, up ? above : below))}px`;
    };
    document.addEventListener('toggle', (event) => {
        const ms = event.target;
        if (!(ms instanceof Element) || !ms.matches('[data-type-ms]')) return;
        if (ms.open) { lift(ms); place(ms); } else { drop(ms); }
    }, true);
    window.addEventListener('resize', () => document.querySelectorAll('[data-type-ms][open]').forEach(place));
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        document.querySelectorAll('[data-type-ms][open]').forEach((ms) => { ms.open = false; ms.querySelector('summary').focus(); });
    });
})();
