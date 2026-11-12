/*
 * Live regions: filters, search, paging and calendar navigation update part of the page
 * without a full reload.
 *
 * Mark the part of the page that changes with an id + data-live-region:
 *     <section id="students-list" data-live-region> ...filters, table, pager... </section>
 * Then, on the same page:
 * - GET forms inside a region (or anywhere, with data-live) are sent with fetch;
 * - links inside a region (or with data-live) that point to this same page with another
 *   query string (?page=2, ?month=5, "?") are followed with fetch;
 * - search boxes in those forms (type=search, name=q, or data-live-input) send while typing.
 * The server renders the normal full page; every region with the same id is taken from the
 * response and swapped in, the address bar is updated (Back/Forward and shared links work).
 * Anything unexpected (other page, redirect to login, file download, error, region missing)
 * falls back to a normal navigation, so pages behave exactly as before in the worst case.
 *
 * data-live-region="contents" makes the region display:contents (no layout box of its own).
 * Regions may be nested (e.g. tabs + tab content around a filtered list); only the outermost
 * ones are swapped, so a tab may render different inner regions than the one before it.
 * Opt out with data-live-skip on a form, link, submit button or input (or an ancestor).
 * After a swap each new region fires a bubbling "mq:live-load" event; global helpers
 * (Persian digits, responsive tables) listen to it. While a load runs the site-wide loader shows
 * (static/js/page-loader.js). Page scripts that bind listeners to
 * elements inside a region must use event delegation or rebind on that event.
 * Inline <script> tags inside a region are not executed after a swap, unless the region has
 * data-live-scripts (only for scripts that bind to elements inside the region).
 * Two pages that look alike may differ only inside a region: keep page-wide scripts outside.
 */
(() => {
    if (window.__mqLiveRegion) return;
    window.__mqLiveRegion = true;
    if (!window.fetch || !window.DOMParser || !window.history || !history.pushState) return;

    // form.requestSubmit() fires the submit event (form.submit() does not); old Safari lacks it.
    if (!HTMLFormElement.prototype.requestSubmit) {
        HTMLFormElement.prototype.requestSubmit = function requestSubmit() {
            const event = new Event('submit', {bubbles: true, cancelable: true});
            if (this.dispatchEvent(event)) this.submit();
        };
    }

    const REGION = '[data-live-region][id]';
    const SKIP = '[data-live-skip]';
    const SEARCH_INPUT = 'input[type="search"], input[name="q"], input[data-live-input]';
    const DEBOUNCE_MS = 450;
    const BUSY_DELAY_MS = 120;

    const style = document.createElement('style');
    // data-live-region="contents": a layout-neutral wrapper (display:contents) around several
    // blocks of a grid/flex page, e.g. tabs + the tab's content.
    style.textContent = '[data-live-region="contents"]{display:contents}'
        + '[data-live-region].is-live-loading,[data-live-region="contents"].is-live-loading>*{opacity:.55;pointer-events:none;transition:opacity .15s ease}'
        + '[data-live-region="contents"].is-live-loading{opacity:1}'
        + '@media (prefers-reduced-motion: reduce){[data-live-region].is-live-loading,[data-live-region="contents"].is-live-loading>*{transition:none}}';
    document.head.appendChild(style);

    // The element that scrolls the page: the panel layouts scroll an inner box (.app-main), others the window.
    const scrollerOf = (el) => {
        for (let n = el && el.parentElement; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
            const oy = getComputedStyle(n).overflowY;
            if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay')
            && n.scrollHeight > n.clientHeight + 1 && n.clientHeight > window.innerHeight / 2) return n; // not a table's sideways box
        }
        return null;
    };
    const scrollTopOf = (sc) => (sc ? sc.scrollTop : window.scrollY);
    const setScrollTop = (sc, y) => (sc ? (sc.scrollTop = y) : window.scrollTo(window.scrollX, y));

    const regions = () => [...document.querySelectorAll(REGION)];
    const hasRegions = () => document.querySelector(REGION) !== null;
    const isLiveScope = (el) => !el.closest(SKIP) && (el.closest(REGION) || el.closest('[data-live]'));

    let controller = null;
    let busyTimer = null;

    const fullNavigation = (url) => {
        if (window.mqLoader) window.mqLoader.nav();
        window.location.assign(url);
    };

    const setBusy = (on) => {
        clearTimeout(busyTimer);
        if (on) {
            busyTimer = setTimeout(() => regions().forEach((el) => {
                el.classList.add('is-live-loading');
                el.setAttribute('aria-busy', 'true');
            }), BUSY_DELAY_MS);
        } else {
            regions().forEach((el) => {
                el.classList.remove('is-live-loading');
                el.removeAttribute('aria-busy');
            });
        }
    };

    // Remember the focused field inside a region so typing can continue after the swap.
    const captureFocus = () => {
        const el = document.activeElement;
        if (!el || el === document.body || !el.closest(REGION)) return null;
        const region = el.closest(REGION);
        let selector = null;
        if (el.id) selector = `#${CSS.escape(el.id)}`;
        else if (el.name) selector = `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
        if (!selector) return null;
        const textual = el.tagName === 'INPUT' && /^(text|search|tel|email|url|number)$/i.test(el.type);
        let start = null;
        let end = null;
        try { start = el.selectionStart; end = el.selectionEnd; } catch (e) { /* not selectable */ }
        return {regionId: region.id, selector, el, textual, start, end};
    };

    const restoreFocus = (saved, keepTyped) => {
        if (!saved) return;
        const region = document.getElementById(saved.regionId);
        const target = region && region.querySelector(saved.selector);
        if (!target) return;
        // a search sent while typing: keep what the user typed while the request was running
        if (keepTyped && saved.textual && target.tagName === 'INPUT') target.value = saved.el.value;
        target.focus({preventScroll: true});
        if (saved.textual && saved.start !== null) {
            try { target.setSelectionRange(saved.start, saved.end); } catch (e) { /* ignore */ }
        }
    };

    // A region may sit inside a bigger one (tabs + content around a filtered list): swap only
    // the outermost ones, so the inner ids may differ between the old and the new page.
    const outerRegions = () => regions().filter((el) => !el.parentElement.closest(REGION));

    // data-live-scripts: re-run the region's own inline classic scripts after a swap (scripts that
    // bind to elements inside the region; document/window listeners there would pile up).
    const runScripts = (root) => {
        root.querySelectorAll('script:not([src])').forEach((old) => {
            const type = (old.getAttribute('type') || '').trim().toLowerCase();
            if (type && type !== 'text/javascript' && type !== 'application/javascript') return;
            const script = document.createElement('script');
            script.textContent = old.textContent;
            old.replaceWith(script);
        });
    };

    const swap = (doc, keepTyped) => {
        const current = outerRegions();
        const pairs = current.map((el) => [el, doc.getElementById(el.id)]);
        if (!pairs.length || pairs.some(([, next]) => !next || !next.matches('[data-live-region]'))) return false;
        const saved = captureFocus();
        const swapped = pairs.map(([el, next]) => {
            const fresh = document.importNode(next, true);
            el.replaceWith(fresh);
            if (fresh.hasAttribute('data-live-scripts')) runScripts(fresh);
            return fresh;
        });
        if (doc.title) document.title = doc.title;
        restoreFocus(saved, keepTyped);
        swapped.forEach((el) => el.dispatchEvent(new CustomEvent('mq:live-load', {bubbles: true})));
        return swapped;
    };

    const load = async (url, {push = true, scrollToRegion = false, fromForm = false, hash = '', target = ''} = {}) => {
        if (controller) controller.abort();
        controller = new AbortController();
        const mine = controller;
        setBusy(true);
        // the site-wide loader (static/js/page-loader.js) runs from the request until the new content is in place
        const task = window.mqLoader ? window.mqLoader.start() : 0;
        try {
            const response = await fetch(url, {
                mqBackground: true,
                credentials: 'same-origin',
                headers: {'X-Requested-With': 'live-region', Accept: 'text/html'},
                signal: mine.signal,
            });
            const finalUrl = new URL(response.url || url, window.location.href);
            const type = response.headers.get('Content-Type') || '';
            // login redirect, another page, a download or an error: let the browser handle it
            if (!response.ok || !type.includes('text/html') || finalUrl.pathname !== new URL(url).pathname) {
                fullNavigation(url);
                return;
            }
            const html = await response.text();
            if (mine !== controller) return;
            const doc = new DOMParser().parseFromString(html, 'text/html');
            // the swapped content is briefly shorter until tables/cards are rebuilt, so the browser clamps
            // and re-anchors the scroll position (the page jumped); keep it where it was instead
            const scroller = scrollerOf(outerRegions()[0]);
            const keepY = scrollTopOf(scroller);
            const swapped = swap(doc, fromForm);
            if (!swapped) {
                fullNavigation(url);
                return;
            }
            const shownUrl = response.redirected ? finalUrl.href : url;
            if (push) history.pushState({mqLive: true}, '', shownUrl + hash);
            else if (shownUrl !== window.location.href) history.replaceState({mqLive: true}, '', shownUrl);
            const boxOf = (el) => (el && el.getAttribute('data-live-region') === 'contents' ? el.firstElementChild : el);
            const first = boxOf((target && document.getElementById(target)) || swapped[0]);
            const anchor = hash && document.getElementById(decodeURIComponent(hash.slice(1)));
            const place = () => {
                setScrollTop(scroller, keepY);
                if (anchor) anchor.scrollIntoView({block: 'start'});
                else if (scrollToRegion && first && first.isConnected) {
                    // paging: back to the top of the list when it is above the visible area (never further down)
                    const viewTop = scroller ? scroller.getBoundingClientRect().top : 0;
                    const top = first.getBoundingClientRect().top - viewTop;
                    if (top < 0) setScrollTop(scroller, scrollTopOf(scroller) + top - (scroller ? 12 : 90));
                }
            };
            place();
            // again after the region's helpers (responsive tables, pager) rebuilt it in microtasks, before the paint
            requestAnimationFrame(place);
        } catch (error) {
            if (error && error.name === 'AbortError') return;
            fullNavigation(url);
        } finally {
            if (task) window.mqLoader.stop(task);
            if (mine === controller) {
                controller = null;
                setBusy(false);
            }
        }
    };

    const formUrl = (form, submitter) => {
        let data;
        try {
            data = new FormData(form, submitter || undefined);
        } catch (e) {
            data = new FormData(form);
            if (submitter && submitter.name) data.append(submitter.name, submitter.value);
        }
        const action = (submitter && submitter.hasAttribute('formaction')) ? submitter.formAction : form.action;
        const url = new URL(action || window.location.href, window.location.href);
        const params = new URLSearchParams();
        for (const [key, value] of data) {
            if (typeof value === 'string') params.append(key, value);
        }
        url.search = params.toString();
        url.hash = '';
        return url.href;
    };

    const liveForm = (form, submitter) => {
        if (!form || !hasRegions() || !isLiveScope(form)) return false;
        if (submitter && submitter.closest(SKIP)) return false;
        const method = ((submitter && submitter.getAttribute('formmethod')) || form.getAttribute('method') || 'get').toLowerCase();
        const target = (submitter && submitter.getAttribute('formtarget')) || form.getAttribute('target') || '';
        if (method !== 'get' || (target && target !== '_self')) return false;
        if ([...form.elements].some((el) => el.type === 'file')) return false;
        return true;
    };

    document.addEventListener('submit', (event) => {
        const form = event.target;
        const submitter = event.submitter || null;
        if (event.defaultPrevented || !liveForm(form, submitter)) return;
        const url = formUrl(form, submitter);
        if (new URL(url).origin !== window.location.origin) return;
        event.preventDefault();
        clearTimeout(form.__mqLiveTimer);
        // a pager made of submit buttons (name="page"): like a paging link
        const paging = !!(submitter && submitter.name === 'page');
        const region = form.closest(REGION);
        load(url, {fromForm: true, scrollToRegion: paging, target: paging && region ? region.id : ''});
    });

    document.addEventListener('click', (event) => {
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const link = event.target.closest && event.target.closest('a[href]');
        if (!link || !hasRegions() || !isLiveScope(link)) return;
        if (link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
        const url = new URL(link.href, window.location.href);
        const here = new URL(window.location.href);
        if (url.origin !== here.origin || url.pathname !== here.pathname) return;
        if (url.search === here.search) return; // "#", "#section" or the same address
        event.preventDefault();
        const hash = url.hash;
        url.hash = '';
        const region = link.closest(REGION);
        load(url.href, {scrollToRegion: true, hash, target: region ? region.id : ''});
    });

    // Search while typing (debounced); Enter still submits immediately through the submit handler.
    document.addEventListener('input', (event) => {
        const input = event.target;
        if (!input.matches || !input.matches(SEARCH_INPUT) || input.closest(SKIP)) return;
        const form = input.form;
        if (!liveForm(form, null)) return;
        clearTimeout(form.__mqLiveTimer);
        form.__mqLiveTimer = setTimeout(() => form.requestSubmit(), DEBOUNCE_MS);
    });

    const markEntry = () => {
        if (hasRegions() && !(history.state && history.state.mqLive)) {
            history.replaceState(Object.assign({}, history.state, {mqLive: true}), '', window.location.href);
        }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', markEntry);
    else markEntry();

    window.addEventListener('popstate', (event) => {
        if (event.state && event.state.mqLive && hasRegions()) load(window.location.href, {push: false});
    });

    // For page scripts: window.mqLive.load('?page=2') or window.mqLive.submit(form)
    window.mqLive = {
        load: (url) => load(new URL(url, window.location.href).href),
        submit: (form) => form.requestSubmit(),
    };
})();
