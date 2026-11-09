/*
 * Count-up animation for dashboard numbers (all roles).
 * - Explicit: any element with data-counter="<number>" (optional data-counter-suffix).
 * - Automatic: numbers inside stat/KPI/metric/tile/count containers whose text holds exactly
 *   one number (e.g. "۱۲", "۸۵٪", "+۵۰", "۳۵ دقیقه"); the surrounding text is kept.
 * Opt out with data-no-count on an element or any ancestor. Countdowns, dates, times
 * ("۱۲:۳۰"), codes (data-latin-digits) and editable fields are never touched.
 * Starts when the number scrolls into view (same timing as the admin dashboard), and runs
 * again whenever it is shown anew: content swapped in by live regions (tabs, filters,
 * paging — "mq:live-load") and hidden content that becomes visible (client-side tabs,
 * collapses, modals). Merely scrolling away and back does not replay it.
 */
(() => {
    if (window.__mqCountUp) return;
    window.__mqCountUp = true;

    const FA = '۰۱۲۳۴۵۶۷۸۹';
    const DURATION = 900;
    const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduceMotion) return;

    const toLatin = (s) => s.replace(/[۰-۹]/g, (d) => String(FA.indexOf(d))).replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)));
    const DIGIT = '0-9۰-۹٠-٩';
    const NUMBER_RE = new RegExp(`[${DIGIT}](?:[${DIGIT},٬]*[${DIGIT}])?(?:[.٫][${DIGIT}]+)?`, 'g');
    const CONTAINER_RE = /(^|[-_])(stat|stats|kpi|kpis|metric|metrics|tile|tiles|counter|count|counts|summary)([-_]|$)/i;
    const VALUE_TAGS = 'strong, b, em, h2, h3, h4, [class*="value"]';
    const SKIP = '[data-no-count], [data-countdown], [data-latin-digits], [contenteditable], .ql-editor, input, select, textarea, option, script, style, time';

    const claimed = new WeakSet();

    const isStatContainer = (el) => {
        for (const token of el.classList) {
            if (CONTAINER_RE.test(token)) return true;
        }
        return false;
    };

    // Builds a job for one text node holding exactly one number.
    const jobFromText = (textNode, host) => {
        if (claimed.has(textNode)) return null;
        const text = textNode.nodeValue;
        const matches = text.match(NUMBER_RE);
        if (!matches || matches.length !== 1) return null;
        const raw = matches[0];
        const index = text.indexOf(raw);
        const before = text.slice(0, index);
        const after = text.slice(index + raw.length);
        // "۱۲:۳۰", "۱۴۰۵/۰۸/۱۷", "۲-۳" style values are not counts.
        if (/[:/\-]\s*$/.test(before) || /^\s*[:/\-]/.test(after)) return null;
        if (text.trim().length > 40) return null;
        const latin = toLatin(raw);
        const grouped = /[,٬]/.test(latin);
        const decimalPart = latin.match(/[.٫](\d+)$/);
        const decimals = decimalPart ? decimalPart[1].length : 0;
        const target = Number(latin.replace(/[,٬]/g, '').replace('٫', '.'));
        if (!Number.isFinite(target) || target === 0) return null;
        // Codes, IDs, phone numbers and Jalali years are not counts.
        const intDigits = latin.replace(/[,٬]/g, '').split(/[.٫]/)[0];
        if (/^0\d/.test(intDigits) || (!grouped && intDigits.length >= 6)) return null;
        if (!grouped && !decimals && intDigits.length === 4 && target >= 1300 && target <= 1500) return null;
        const persian = /[۰-۹٠-٩]/.test(raw) || !host.closest('[data-latin-digits]');
        claimed.add(textNode);
        return {textNode, host, before, after, target, decimals, grouped, persian};
    };

    const formatter = (job) => new Intl.NumberFormat(job.persian ? 'fa-IR' : 'en-US', {
        minimumFractionDigits: job.decimals,
        maximumFractionDigits: job.decimals,
        useGrouping: job.grouped,
    });

    const run = (job) => {
        const fmt = formatter(job);
        const finalText = job.before + fmt.format(job.target) + job.after;
        const start = performance.now();
        const runId = (job.runId || 0) + 1;
        job.runId = runId;
        const tick = (now) => {
            if (job.runId !== runId) return;
            const progress = Math.min((now - start) / DURATION, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            job.textNode.nodeValue = progress < 1
                ? job.before + fmt.format(job.decimals ? job.target * eased : Math.round(job.target * eased)) + job.after
                : finalText;
            if (progress < 1) requestAnimationFrame(tick);
        };
        job.textNode.nodeValue = job.before + fmt.format(0) + job.after;
        requestAnimationFrame(tick);
    };

    const within = (root, selector) => {
        const found = Array.from(root.querySelectorAll(selector));
        if (root.matches && root.matches(selector)) found.unshift(root);
        return found;
    };

    const collectExplicit = (root, jobs) => {
        within(root, '[data-counter]').forEach((node) => {
            if (node.closest(SKIP) || node.dataset.counterDone === '1') return;
            const target = Number(toLatin(String(node.dataset.counter || '')).replace(/[^\d.-]/g, ''));
            if (!Number.isFinite(target) || target === 0) return;
            node.dataset.counterDone = '1';
            const suffix = node.dataset.counterSuffix || '';
            const prefix = node.dataset.counterPrefix || '';
            const decimals = Number.isInteger(target) ? 0 : 1;
            const job = {host: node, before: prefix, after: suffix, target, decimals, grouped: true, persian: true};
            job.textNode = document.createTextNode(prefix + formatter(job).format(target) + suffix);
            node.textContent = '';
            node.appendChild(job.textNode);
            claimed.add(job.textNode);
            jobs.push(job);
        });
    };

    const collectAuto = (root, jobs) => {
        const containers = within(root, '[class]').filter(isStatContainer);
        // A swapped region may sit inside a stat container.
        for (let el = root.parentElement; el; el = el.parentElement) {
            if (el.classList && isStatContainer(el)) { containers.unshift(el); break; }
        }
        containers.forEach((container) => {
            if (container.closest(SKIP)) return;
            const valueHosts = Array.from(container.querySelectorAll(VALUE_TAGS));
            if (container.matches(VALUE_TAGS)) valueHosts.unshift(container);
            valueHosts.forEach((host) => {
                if (host.closest(SKIP) || host.querySelector(SKIP)) return;
                // Only the host's own text: one text node with digits among its descendants.
                const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
                const withDigits = [];
                while (walker.nextNode()) {
                    if (/[0-9۰-۹٠-٩]/.test(walker.currentNode.nodeValue)) withDigits.push(walker.currentNode);
                }
                if (withDigits.length !== 1) return;
                const job = jobFromText(withDigits[0], host);
                if (job) jobs.push(job);
            });
        });
    };

    // host -> {jobs, seen, hidden}. Kept observed: plays on first view and again each time the
    // host comes back from being hidden (display:none gives an empty rect).
    const hosts = new Map();
    const observer = 'IntersectionObserver' in window ? new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            const state = hosts.get(entry.target);
            if (!state) return;
            if (!entry.target.isConnected) {
                observer.unobserve(entry.target);
                hosts.delete(entry.target);
                return;
            }
            const rect = entry.boundingClientRect;
            if (entry.isIntersecting) {
                if (!state.seen || state.hidden) state.jobs.forEach(run);
                state.seen = true;
                state.hidden = false;
            } else if (!rect.width && !rect.height) {
                state.hidden = true;
            }
        });
    }, {threshold: 0.35}) : null;

    const scan = (root) => {
        const jobs = [];
        collectExplicit(root, jobs);
        collectAuto(root, jobs);
        jobs.forEach((job) => {
            let state = hosts.get(job.host);
            if (!state) {
                state = {jobs: [], seen: false, hidden: false};
                hosts.set(job.host, state);
                if (observer) observer.observe(job.host);
            }
            state.jobs.push(job);
            if (!observer) run(job);
        });
    };

    const start = () => {
        scan(document);
        // Live regions (tabs, filters, paging) swap in new content without a reload.
        document.addEventListener('mq:live-load', (event) => {
            hosts.forEach((_, host) => {
                if (!host.isConnected) {
                    if (observer) observer.unobserve(host);
                    hosts.delete(host);
                }
            });
            if (event.target && event.target.querySelectorAll) scan(event.target);
        });
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
