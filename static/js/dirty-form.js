/*
 * Dirty forms: a form's «ذخیره» / «اعمال فیلتر» button stays disabled until something in the form differs from what
 * the form showed when it was loaded, and goes back to disabled when the change is undone (user's requirement).
 *
 *   <form method="post" data-dirty-form>
 *       …fields…
 *       <button data-dirty-submit>ذخیره تغییرات</button>
 *       <button type="button" data-dirty-reset>بازنشانی</button>
 *   </form>
 *
 * - data-dirty-submit: disabled while the form is clean; disabled again as soon as the form is sent through it (or by
 *   Enter), so it can't be sent twice. Other submit buttons of the form (e.g. «خروجی فایل») are left alone.
 * - data-dirty-reset: puts every field back to its loaded value, client-side (no reload), then fires input/change on
 *   the restored fields and "mq:dirty-reset" on the form so page scripts (switches, previews) follow; disabled while
 *   the form is clean.
 * - Compared: every named field (text, number, select, checkbox, radio, hidden, file — a chosen file counts as a
 *   change) plus [contenteditable][data-dirty-field]. Skip a field with data-dirty-ignore. Hidden inputs that page
 *   scripts change (switches, date pickers) are watched too, no event needed.
 * - Every state change fires "mq:dirty-change" on the form (detail: {dirty}); the form gets data-dirty="1" while dirty.
 * - The baseline is taken on DOMContentLoaded, and again for forms inside a live region after it is swapped in
 *   (mq:live-load). A form sent through a live region (GET filter) takes what it sent as its new baseline.
 *   Page scripts that load a form later call window.mqDirtyForm.init(root); window.mqDirtyForm.rebase(form) accepts the
 *   current values as saved.
 */
(() => {
    if (window.mqDirtyForm) return;

    const FORM = 'form[data-dirty-form]';
    const SKIP_TYPES = new Set(['submit', 'button', 'reset', 'image']);
    const states = new WeakMap(); // form → {base: Map(field → value), dirty, sending, observer}

    const fieldsOf = (form) => {
        const list = [];
        for (const el of form.elements) {
            if (!el.name || SKIP_TYPES.has(el.type) || el.matches('fieldset, output, object, [data-dirty-ignore]')) continue;
            list.push(el);
        }
        form.querySelectorAll('[contenteditable][data-dirty-field]:not([data-dirty-ignore])').forEach((el) => list.push(el));
        return list;
    };

    const valueOf = (el) => {
        if (el.isContentEditable || el.hasAttribute('contenteditable')) return el.innerHTML;
        if (el.type === 'checkbox' || el.type === 'radio') return el.checked;
        if (el.type === 'file') return Array.from(el.files || []).map((f) => `${f.name}:${f.size}`).join('|');
        if (el.tagName === 'SELECT' && el.multiple) return Array.from(el.selectedOptions).map((o) => o.value).join('\u0001');
        return el.value;
    };

    const buttons = (form, attr) => {
        const own = Array.from(form.querySelectorAll(`[${attr}]`));
        // buttons outside the form that name it (form="id")
        if (form.id) document.querySelectorAll(`[${attr}][form="${CSS.escape(form.id)}"]`).forEach((b) => own.includes(b) || own.push(b));
        return own;
    };

    const paint = (form, state) => {
        const off = !state.dirty || state.sending;
        buttons(form, 'data-dirty-submit').forEach((b) => { b.disabled = off; });
        buttons(form, 'data-dirty-reset').forEach((b) => { b.disabled = off; });
        form.toggleAttribute('data-dirty', state.dirty);
    };

    const check = (form) => {
        const state = states.get(form);
        if (!state) return;
        let dirty = false;
        const fields = fieldsOf(form);
        if (fields.length !== state.base.size) dirty = true;
        else {
            for (const el of fields) {
                if (!state.base.has(el) || state.base.get(el) !== valueOf(el)) { dirty = true; break; }
            }
        }
        const changed = dirty !== state.dirty;
        state.dirty = dirty;
        paint(form, state);
        if (changed) form.dispatchEvent(new CustomEvent('mq:dirty-change', {bubbles: true, detail: {dirty}}));
    };

    const rebase = (form) => {
        const state = states.get(form);
        if (!state) return;
        state.base = new Map(fieldsOf(form).map((el) => [el, valueOf(el)]));
        state.sending = false;
        state.dirty = false;
        paint(form, state);
    };

    const setup = (form) => {
        if (states.has(form)) { rebase(form); return; }
        const state = {base: new Map(), dirty: false, sending: false, observer: null};
        states.set(form, state);
        // scripts that set hidden inputs (switches, date pickers) change the value attribute: no event is fired
        state.observer = new MutationObserver(() => check(form));
        state.observer.observe(form, {subtree: true, attributes: true, attributeFilter: ['value', 'checked', 'selected'], childList: true, characterData: true});
        rebase(form);
    };

    const init = (root) => {
        const scope = root && root.querySelectorAll ? root : document;
        if (scope.matches && scope.matches(FORM)) setup(scope);
        scope.querySelectorAll(FORM).forEach(setup);
    };

    const reset = (form) => {
        const state = states.get(form);
        if (!state) return;
        const touched = [];
        state.base.forEach((value, el) => {
            if (!el.isConnected || valueOf(el) === value) return;
            if (el.isContentEditable || el.hasAttribute('contenteditable')) el.innerHTML = value;
            else if (el.type === 'checkbox' || el.type === 'radio') el.checked = value;
            else if (el.type === 'file') el.value = '';
            else if (el.tagName === 'SELECT' && el.multiple) {
                const chosen = new Set(String(value).split('\u0001'));
                Array.from(el.options).forEach((o) => { o.selected = chosen.has(o.value); });
            } else el.value = value;
            touched.push(el);
        });
        touched.forEach((el) => {
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        });
        form.dispatchEvent(new CustomEvent('mq:dirty-reset', {bubbles: true}));
        check(form);
    };

    const formOf = (el) => {
        if (!el || !el.closest) return null;
        const owner = el.form || el.closest('form');
        return owner && states.has(owner) ? owner : null;
    };

    ['input', 'change'].forEach((type) => document.addEventListener(type, (event) => {
        const form = formOf(event.target);
        if (form) check(form);
    }));

    document.addEventListener('click', (event) => {
        const resetButton = event.target.closest && event.target.closest('[data-dirty-reset]');
        if (resetButton) {
            const form = resetButton.form || resetButton.closest('form');
            if (form && states.has(form)) {
                event.preventDefault();
                reset(form);
                return;
            }
        }
        const form = formOf(event.target);
        if (form) check(form); // e.g. a switch button that flips a hidden input
    });

    const isLiveGet = (form) => (form.method || 'get').toLowerCase() === 'get'
        && !form.closest('[data-live-skip]')
        && (form.hasAttribute('data-live') || !!form.closest('[data-live-region][id]'));

    document.addEventListener('submit', (event) => {
        const form = event.target;
        const state = states.get(form);
        if (!state) return;
        const submitter = event.submitter;
        if (submitter && !submitter.hasAttribute('data-dirty-submit')) return; // «خروجی فایل» and the like
        // decide after every submit handler ran (a page check may cancel it; live-region.js cancels it to fetch)
        window.setTimeout(() => {
            if (event.defaultPrevented && !isLiveGet(form)) return;
            state.sending = true;
            paint(form, state);
        }, 0);
    });

    document.addEventListener('mq:live-load', (event) => {
        init(event.target);
        // a form outside the swapped region that was sent through it: what it sent is now the applied state
        document.querySelectorAll(FORM).forEach((form) => {
            const state = states.get(form);
            if (state && state.sending) rebase(form);
        });
    });

    // Back to a page kept in the browser's cache: the form may have been sent from it
    window.addEventListener('pageshow', (event) => {
        if (!event.persisted) return;
        document.querySelectorAll(FORM).forEach((form) => {
            const state = states.get(form);
            if (state) { state.sending = false; check(form); }
        });
    });

    window.mqDirtyForm = {init, rebase, reset, check, isDirty: (form) => !!(states.get(form) || {}).dirty};

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => init(document));
    else init(document);
})();
