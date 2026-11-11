/*
 * Site-wide loader: the MetaQuizy mark in a spinning ring, centred on the screen, shown for exactly as long as
 * something is loading (static/css/page-loader.css; included by partials/appearance_head.html on every page).
 *
 * When: it appears the moment the user acts (click, submit, Back, refresh…) and goes the moment the result is on
 * screen; it never appears on its own. MIN_VISIBLE only stops a one-frame flicker for instant loads.
 * - leaving the page in any way: links, form submits (also form.submit()), location.assign/reload, Back/Forward,
 *   refresh, the address bar (beforeunload); it stays up until the next page is shown, where it is already on from
 *   the first moment (first paint, partials/appearance_head.html calls bootDone() when the page is revealed);
 * - live regions (static/js/live-region.js): filters, search, paging, calendar and tabs;
 * - fetch()/XMLHttpRequest started by the user (dialogs, wizards, uploads, the attempt page's question switch…).
 *   Not: fetch(url, {mqBackground: true, …}) (autosave, polling, attempt events) or requests a script makes on its own.
 * While a text field has focus (search while typing) it does not block the mouse.
 *
 * Nothing loads in this page for target=_blank (the new tab shows its own), in-page #anchors, mailto:/tel:.
 * Files (download links, /media/, .xlsx, .pdf…): a download served by Django answers with the mq_dl cookie
 * (apps/core/middleware.py), which hides the loader the moment the file starts; other files give up after
 * FILE_TIMEOUT. A «leave this page?» prompt answered «stay», Esc, and a bfcache restore hide it too.
 * [data-no-loader] opts an element out (nothing uses it today).
 *
 * For page scripts: const id = mqLoader.start(); … mqLoader.stop(id);  or  mqLoader.track(promise);
 */
(() => {
    'use strict';
    if (window.mqLoader) return;

    const root = document.documentElement;
    const FILE_TIMEOUT = 8000;
    const MIN_VISIBLE = 200;  // a load that ends at once still shows a whole spin, not a one-frame flicker
    const HIDE_GRACE = 0;     // fetch() keeps its own 60ms after the response, so fetch → fetch stays one loader
    const FADE = 150;
    const GESTURE_WINDOW = 1500; // a request sent this long after a click/key/submit belongs to that action
    const NAV_FAILSAFE = 30000;
    const TASK_FAILSAFE = 45000;
    const NAV_KEY = 'mq-loader-nav'; // left over from an older version: removed on load
    const FILE_URL = /(^\/media\/)|\.(xlsx?|docx?|pptx?|csv|pdf|zip|rar|json|txt|mp3|mp4|wav|m4a|ogg|webm|png|jpe?g|gif|svg|webp)$/i;
    const TEXT = 'در حال بارگذاری';

    const popover = typeof HTMLElement !== 'undefined' && Object.prototype.hasOwnProperty.call(HTMLElement.prototype, 'popover');
    const tasks = new Map();
    let seq = 0;
    let el = null;
    let label = null;
    let visible = false;
    let shownAt = 0;
    let quickHide = false;
    let showTimer = 0;
    let hideTimer = 0;
    let fadeTimer = 0;
    let navId = 0;
    let dlTimer = 0;

    const MARKUP = '<div class="mq-loader__veil"></div>'
        + '<div class="mq-loader__card">'
        + '<div class="mq-loader__logo" aria-hidden="true"><span class="mq-loader__track"></span><span class="mq-loader__ring"></span>'
        + '<span class="mq-loader__mark"><svg viewBox="0 0 24 24" focusable="false">'
        + '<rect x="3.6" y="3.6" width="6.8" height="6.8" rx="2" fill="none" stroke="#fff" stroke-width="1.9"/>'
        + '<rect x="13.2" y="3.2" width="7.6" height="7.6" rx="2.2" fill="#fff"/>'
        + '<circle cx="7" cy="17" r="3.8" fill="#fff" fill-opacity=".92"/>'
        + '<path d="M13.4 17.1l2.4 2.4 4.6-5" fill="none" stroke="#fff" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>'
        + '</svg></span></div>'
        + '<div class="mq-loader__name" aria-hidden="true">متاکوییز</div>'
        + '<div class="mq-loader__text"><span class="mq-loader__label"></span><span class="mq-loader__dots" aria-hidden="true"><i></i><i></i><i></i></span></div>'
        + '</div>';

    // Kept outside <body> (a child of <html>): the first-paint gate hides <body>, and live swaps never touch it.
    const build = () => {
        if (!el) {
            el = document.createElement('div');
            el.id = 'mq-page-loader';
            el.className = 'mq-loader';
            el.setAttribute('role', 'status');
            el.setAttribute('aria-live', 'polite');
            if (popover) el.setAttribute('popover', 'manual');
            el.innerHTML = MARKUP;
        }
        if (!el.isConnected) root.appendChild(el);
        return el;
    };

    const typing = () => {
        const a = document.activeElement;
        if (!a || a === document.body) return false;
        if (a.isContentEditable || a.tagName === 'TEXTAREA') return true;
        return a.tagName === 'INPUT' && /^(text|search|tel|email|url|number|password)$/i.test(a.type);
    };

    const openPopover = (raise) => {
        if (!popover) return;
        try {
            const open = el.matches(':popover-open');
            // a <dialog> opened after the loader sits above it in the top layer: put the loader back on top
            if (open && raise && document.querySelector('dialog[open]')) el.hidePopover();
            if (!el.matches(':popover-open')) el.showPopover();
        } catch (e) { /* not connected yet / unsupported */ }
    };

    const updateMode = () => {
        if (!el || !tasks.size) return;
        const list = [...tasks.values()];
        const kind = list.some((t) => t.kind === 'nav') ? 'nav' : (list.some((t) => t.kind === 'boot') ? 'boot' : 'task');
        el.dataset.kind = kind;
        el.classList.toggle('is-passive', list.every((t) => t.passive));
        const withLabel = list.filter((t) => t.label).pop();
        const text = withLabel ? withLabel.label : TEXT;
        if (text !== label) {
            label = text;
            el.querySelector('.mq-loader__label').textContent = text;
        }
    };

    const show = (instant, raise) => {
        clearTimeout(showTimer);
        showTimer = 0;
        clearTimeout(hideTimer);
        clearTimeout(fadeTimer);
        build();
        updateMode();
        openPopover(raise);
        if (visible) { el.classList.add('is-open'); return; }
        visible = true;
        shownAt = Date.now();
        el.classList.toggle('is-instant', !!instant);
        void el.offsetWidth; // start the fade-in from opacity 0
        el.classList.add('is-open');
        if (instant) requestAnimationFrame(() => requestAnimationFrame(() => el && el.classList.remove('is-instant')));
    };

    const finishHide = () => {
        visible = false;
        quickHide = false;
        if (!el) return;
        el.classList.remove('is-open', 'is-instant', 'is-passive');
        if (popover) { try { if (el.matches(':popover-open')) el.hidePopover(); } catch (e) { /* ignore */ } }
    };

    const scheduleHide = () => {
        clearTimeout(showTimer);
        showTimer = 0;
        if (!visible) return;
        clearTimeout(hideTimer);
        const wait = quickHide ? 0 : Math.max(HIDE_GRACE, MIN_VISIBLE - (Date.now() - shownAt));
        hideTimer = setTimeout(() => {
            if (tasks.size) return;
            el.classList.remove('is-open');
            fadeTimer = setTimeout(finishHide, FADE);
        }, wait);
    };

    const start = (opts = {}) => {
        const id = ++seq;
        const kind = opts.kind || 'task';
        const task = {
            kind,
            label: opts.label || null,
            passive: opts.passive === undefined ? (kind === 'task' && typing()) : !!opts.passive,
            quick: !!opts.quick,
        };
        task.failsafe = setTimeout(() => stop(id), opts.timeout || (kind === 'nav' ? NAV_FAILSAFE : TASK_FAILSAFE));
        tasks.set(id, task);
        quickHide = false;
        if (visible) show(false, true);
        else if (!opts.delay) show(!!opts.instant, true);
        else if (!showTimer) {
            showTimer = setTimeout(() => { showTimer = 0; if (tasks.size) show(false, true); }, opts.delay);
        }
        return id;
    };

    function stop(id) {
        const task = tasks.get(id);
        if (!task) return;
        clearTimeout(task.failsafe);
        tasks.delete(id);
        if (id === navId) endNavWatch();
        if (tasks.size) { updateMode(); return; }
        if (task.quick) quickHide = true;
        scheduleHide();
    }

    const track = (promise, opts) => {
        const id = start(opts);
        Promise.resolve(promise).then(() => stop(id), () => stop(id));
        return promise;
    };

    // ----- leaving the page -----
    const storage = (fn) => { try { return fn(window.sessionStorage); } catch (e) { return null; } };
    const readCookie = () => {
        const m = document.cookie.match(/(?:^|;\s*)mq_dl=([^;]*)/);
        return m ? m[1] : '';
    };

    function endNavWatch() {
        navId = 0;
        clearInterval(dlTimer);
        dlTimer = 0;
    }

    const cancelNav = () => {
        storage((s) => s.removeItem(NAV_KEY));
        if (navId) stop(navId);
    };

    const nav = (opts = {}) => {
        if (navId && tasks.has(navId)) {
            const task = tasks.get(navId);
            if (opts.timeout) { clearTimeout(task.failsafe); task.failsafe = setTimeout(cancelNav, opts.timeout); }
            return navId;
        }
        navId = start({kind: 'nav', label: opts.label, delay: opts.delay, timeout: opts.timeout});
        // the response turned out to be a file download: the page stays, so does nothing else
        const before = readCookie();
        dlTimer = setInterval(() => { if (readCookie() !== before) cancelNav(); }, 200);
        return navId;
    };

    // What following an address does to this page: 'page' (another page loads), 'file' (a file may open here or
    // download, so the page may stay: the loader gives up after FILE_TIMEOUT unless the mq_dl cookie ends it sooner)
    // or null (nothing loads here: mailto:/tel:/javascript:, an in-page #anchor).
    const classify = (href, source, rawHref) => {
        let url;
        try { url = new URL(href, window.location.href); } catch (e) { return null; }
        if (!/^https?:$/.test(url.protocol)) return null;
        if (source && source.closest && source.closest('[data-no-loader]')) return null;
        const here = window.location;
        const samePage = url.origin === here.origin && url.pathname === here.pathname && url.search === here.search;
        if (samePage && (url.hash || (rawHref && rawHref.indexOf('#') !== -1))) return null;
        return FILE_URL.test(url.pathname) ? 'file' : 'page';
    };
    const navFor = (kind, extra) => {
        if (!kind) return 0;
        return nav(Object.assign({timeout: kind === 'file' ? FILE_TIMEOUT : undefined}, extra || {}));
    };

    const selfTarget = (target) => !target || /^_(self|top|parent)$/i.test(target);

    const formLeaves = (form, submitter) => {
        if (!form || form.closest('[data-no-loader]') || (submitter && submitter.closest('[data-no-loader]'))) return false;
        const target = (submitter && submitter.getAttribute('formtarget')) || form.getAttribute('target') || '';
        const method = ((submitter && submitter.getAttribute('formmethod')) || form.getAttribute('method') || 'get').toLowerCase();
        if (!selfTarget(target) || method === 'dialog') return false; // a new tab shows its own loader
        const action = submitter && submitter.hasAttribute('formaction') ? submitter.formAction : (form.getAttribute('action') ? form.action : window.location.href);
        return !!navFor(classify(action, null, null), {label: method === 'post' ? 'در حال ارسال' : null});
    };

    // The last link clicked, so beforeunload (it runs before the deferred click check) knows where it leads.
    let lastClick = {at: 0, kind: null};

    // Decided after the event finished dispatching, so a later handler's preventDefault() still counts.
    window.addEventListener('click', (event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const link = event.target && event.target.closest && event.target.closest('a[href]');
        if (!link || !selfTarget(link.getAttribute('target'))) return; // a new tab shows its own loader
        let kind = classify(link.href, link, link.getAttribute('href'));
        if (kind && link.hasAttribute('download')) kind = 'file';
        lastClick = {at: Date.now(), kind};
        setTimeout(() => { if (!event.defaultPrevented) navFor(kind); }, 0);
    });

    window.addEventListener('submit', (event) => {
        const form = event.target;
        const submitter = event.submitter || null;
        setTimeout(() => { if (!event.defaultPrevented) formLeaves(form, submitter); }, 0);
    });

    const nativeSubmit = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function submit() {
        try { formLeaves(this, null); } catch (e) { /* never block the submit */ }
        return nativeSubmit.apply(this, arguments);
    };

    // location.assign()/reload() and anything else that leaves the page (Chromium's Navigation API)
    if (window.navigation && typeof window.navigation.addEventListener === 'function') {
        window.navigation.addEventListener('navigate', (event) => {
            if (event.hashChange || (event.destination && event.destination.sameDocument)) return;
            const url = event.destination && event.destination.url;
            const kind = event.downloadRequest != null ? 'file' : classify(url, event.sourceElement || null, null);
            setTimeout(() => { if (!event.defaultPrevented) navFor(kind); }, 0);
        });
    }

    // Every other way of leaving: Back/Forward, refresh, the address bar, scripts. A «leave this page?» prompt (the
    // exam attempt) answered with «stay» keeps the page: checked after the prompt, once every handler has run.
    window.addEventListener('beforeunload', (event) => {
        const recent = lastClick.at && Date.now() - lastClick.at < 1000;
        if (!(recent && lastClick.kind === null)) navFor(recent ? lastClick.kind : 'page');
        setTimeout(() => {
            const value = event.returnValue;
            if (event.defaultPrevented || (typeof value === 'string' && value !== '') || value === false) cancelNav();
        }, 0);
    });

    document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && navId) cancelNav(); });

    // Back/Forward restored this page from the cache: nothing is loading any more
    window.addEventListener('pageshow', (event) => {
        if (!event.persisted) return;
        storage((s) => s.removeItem(NAV_KEY));
        [...tasks.keys()].forEach((id) => { clearTimeout(tasks.get(id).failsafe); tasks.delete(id); });
        endNavWatch();
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
        clearTimeout(fadeTimer);
        showTimer = 0;
        finishHide();
    });

    // ----- requests: shown when the user started them (a click, key, submit or change just before, or while the loader
    // is already up for that action). Requests nobody asked for — fetch(url, {mqBackground: true}) (autosave, polling,
    // attempt events) and scripts loading data on their own after the page opened — never show it. -----
    let gestureAt = 0;
    ['pointerdown', 'click', 'keydown', 'submit', 'change', 'input'].forEach((type) => {
        window.addEventListener(type, (event) => { if (event.isTrusted) gestureAt = Date.now(); }, {capture: true, passive: true});
    });
    const userAction = () => tasks.size > 0 || Date.now() - gestureAt < GESTURE_WINDOW;

    const nativeFetch = window.fetch;
    if (typeof nativeFetch === 'function') {
        window.fetch = function fetch(input, init) {
            if ((init && init.mqBackground) || !userAction()) return nativeFetch.apply(this, arguments);
            const id = start();
            let request;
            try { request = nativeFetch.apply(this, arguments); } catch (error) { stop(id); throw error; }
            // the caller reads and renders the response right after: keep the loader through that
            request.then(() => setTimeout(() => stop(id), 60), () => stop(id));
            return request;
        };
    }
    if (window.XMLHttpRequest) {
        const nativeSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function send() {
            if (!userAction()) return nativeSend.apply(this, arguments);
            const id = start();
            this.addEventListener('loadend', () => setTimeout(() => stop(id), 60), {once: true});
            try { return nativeSend.apply(this, arguments); } catch (error) { stop(id); throw error; }
        };
    }

    // ----- first paint -----
    // On from the first moment (no gap after the previous page's loader), off the moment the page is shown.
    storage((s) => s.removeItem(NAV_KEY));
    const bootId = start({kind: 'boot', instant: true, quick: true, passive: false});
    const bootDone = () => stop(bootId);
    window.addEventListener('load', bootDone);

    window.mqLoader = {start, stop, track, nav, cancelNav, bootDone};
})();
