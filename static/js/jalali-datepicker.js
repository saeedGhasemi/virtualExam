// Jalali (Shamsi) date + time picker on [data-jalali-field] (display box + hidden value "YYYY-MM-DDTHH:MM", Tehran wall time).
//
// Time: hour / minute are lists (00–23, 00–59), so nothing but a valid time can be entered — no typing, no pasted
// text (teacher's report 01-04). Nothing is written until «تأیید»; clicking outside / Escape keeps the old value.
// Limits (teacher's report 01-04…01-07), all optional, combined (latest min, earliest max):
//   data-jalali-min="now"         nothing before the current minute (Tehran): past days / hours / minutes are disabled
//   data-jalali-max-days="365"    nothing after now + N days
//   root.mqJalaliBounds = () => ({min, max, minLabel, maxLabel})   page rules as wallMinute() numbers (null = open),
//                                 e.g. «آخرین زمان مجاز ورود» between the exam's start and end (exam_wizard.html)
// Days outside the range are disabled, months entirely outside can't be opened, the range is written under the
// calendar, and «تأیید» refuses a time outside it with a message. A saved value outside it is still shown as it is
// and «تأیید» keeps it unchanged (an exam whose start has passed can still be edited; the server has the same rule).
import { toJalaali, toGregorian, jalaaliMonthLength } from './vendor/jalaali.js';

const WEEKDAYS = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج'];
const MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
const FA_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];

function toFaDigits(input) {
    return String(input).replace(/[0-9]/g, (d) => FA_DIGITS[d]);
}

function pad2(n) {
    return String(n).padStart(2, '0');
}

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, Number.isFinite(value) ? value : min));
}

function jalaaliWeekday(gy, gm, gd) {
    const jsDay = new Date(Date.UTC(gy, gm - 1, gd)).getUTCDay();
    return (jsDay + 1) % 7;
}

// The site's clock is Tehran's, whatever time zone the visitor's device is set to.
const TEHRAN_PARTS = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Tehran', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

export function tehranParts(moment = new Date()) {
    const parts = Object.fromEntries(TEHRAN_PARTS.formatToParts(moment).map((part) => [part.type, part.value]));
    return { gy: +parts.year, gm: +parts.month, gd: +parts.day, hh: +parts.hour % 24, mm: +parts.minute };
}

// "YYYY-MM-DD[THH:MM]" without an offset is already Tehran wall time (what the server and this picker write);
// with Z or an offset it is a moment, shown at Tehran time.
export function wallParts(value) {
    const text = String(value || '');
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(text);
    if (!match) return null;
    if (/(Z|[+-]\d{2}:?\d{2})$/.test(text)) {
        const moment = new Date(text);
        return Number.isNaN(moment.getTime()) ? null : tehranParts(moment);
    }
    return { gy: +match[1], gm: +match[2], gd: +match[3], hh: +(match[4] || 0), mm: +(match[5] || 0) };
}

// Minutes since 1970-01-01 00:00 of a Tehran wall time (a value string or {gy, gm, gd, hh, mm}); wall-clock
// arithmetic only, so the device's own time zone never matters.
export function wallMinute(value) {
    const d = typeof value === 'string' ? wallParts(value) : value;
    if (!d) return null;
    return Date.UTC(d.gy, d.gm - 1, d.gd, d.hh || 0, d.mm || 0) / 60000;
}

function minuteParts(minute) {
    const t = new Date(minute * 60000);
    return { gy: t.getUTCFullYear(), gm: t.getUTCMonth() + 1, gd: t.getUTCDate(), hh: t.getUTCHours(), mm: t.getUTCMinutes() };
}

function jalaliMinute(j) {
    const g = toGregorian(j.jy, j.jm, j.jd);
    return Date.UTC(g.gy, g.gm - 1, g.gd, j.hh || 0, j.mm || 0) / 60000;
}

function minuteJalali(minute) {
    const p = minuteParts(minute);
    const j = toJalaali(p.gy, p.gm, p.gd);
    return { jy: j.jy, jm: j.jm, jd: j.jd, hh: p.hh, mm: p.mm };
}

// "۱۴۰۵/۰۹/۰۱ - ۰۸:۳۰" for a wall minute.
export function formatWallMinute(minute) {
    const j = minuteJalali(minute);
    return toFaDigits(`${j.jy}/${pad2(j.jm)}/${pad2(j.jd)} - ${pad2(j.hh)}:${pad2(j.mm)}`);
}

let stylesAdded = false;
function addStyles() {
    if (stylesAdded) return;
    stylesAdded = true;
    const style = document.createElement('style');
    style.textContent = '.jalali-popup{max-width:calc(100vw - 24px);box-sizing:border-box}'
        + '.jalali-day:disabled,.jalali-day:disabled:hover{color:#c4cbd8;background:transparent;cursor:not-allowed}'
        + '.jalali-popup-head button:disabled,.jalali-popup-head button:disabled:hover{opacity:.35;cursor:not-allowed;background:#fff;border-color:#d7dfea}'
        + '.jalali-time-row select{height:2.25rem;width:100%;min-width:0;border:1px solid #d7dfea;border-radius:.5rem;background:#fff;'
        + 'padding:0 .4rem;font:inherit;font-size:.9rem;font-weight:700;color:#0b1628;text-align:center;cursor:pointer}'
        + '.jalali-time-row select:focus{outline:2px solid #4b46ff;outline-offset:1px}'
        + '.jalali-range-note{margin:.6rem 0 0;font-size:.74rem;font-weight:400;line-height:1.7;color:#65728a}'
        + '.jalali-popup .mq-rule-msg{margin-top:.5rem}';
    document.head.appendChild(style);
}

class JalaliDateTimeField {
    constructor(root) {
        this.root = root;
        this.display = root.querySelector('[data-jalali-display]');
        this.hidden = root.querySelector('[data-jalali-value]');
        this.dateOnly = root.hasAttribute('data-jalali-date-only'); // filters: day only, hidden value YYYY-MM-DD
        this.popup = null;
        this.viewJy = null;
        this.viewJm = null;
        this.selected = null; // the saved value {jy, jm, jd, hh, mm}
        this.draft = null;    // what the open calendar shows; becomes `selected` on «تأیید»
        this.error = '';

        this.display.addEventListener('click', () => this.toggle());
        this.display.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowDown') { event.preventDefault(); this.open(); }
            if (event.key === 'Escape') this.close();
        });
        document.addEventListener('click', (event) => {
            if (this.popup && !event.composedPath().includes(this.root)) this.close();
        });

        if (this.hidden.value) this.setFromIso(this.hidden.value);
    }

    setFromIso(iso) {
        const d = wallParts(this.dateOnly ? iso.slice(0, 10) : iso);
        if (!d) return;
        const j = toJalaali(d.gy, d.gm, d.gd);
        this.selected = { jy: j.jy, jm: j.jm, jd: j.jd, hh: d.hh, mm: d.mm };
        this.updateDisplay();
    }

    updateDisplay() {
        if (!this.selected) return;
        const { jy, jm, jd, hh, mm } = this.selected;
        this.display.value = toFaDigits(`${jy}/${pad2(jm)}/${pad2(jd)} - ${pad2(hh)}:${pad2(mm)}`);
        const g = toGregorian(jy, jm, jd);
        if (this.dateOnly) {
            this.display.value = toFaDigits(`${jy}/${pad2(jm)}/${pad2(jd)}`);
            this.hidden.value = `${g.gy}-${pad2(g.gm)}-${pad2(g.gd)}`;
            this.hidden.dispatchEvent(new Event('change', { bubbles: true }));
            return;
        }
        this.hidden.value = `${g.gy}-${pad2(g.gm)}-${pad2(g.gd)}T${pad2(hh)}:${pad2(mm)}`;
        this.hidden.dispatchEvent(new Event('change', { bubbles: true }));
    }

    toggle() {
        if (this.popup) this.close();
        else this.open();
    }

    // The allowed range as wall minutes {min, max, minLabel, maxLabel}; null ends are open. Read at every render, so
    // it follows the page's other fields and the clock.
    bounds() {
        let min = null;
        let max = null;
        let minLabel = '';
        let maxLabel = '';
        const now = wallMinute(tehranParts());
        if (this.root.dataset.jalaliMin === 'now') { min = now; minLabel = 'اکنون'; }
        const days = Number(this.root.dataset.jalaliMaxDays);
        if (days > 0) max = now + days * 1440;
        const extra = typeof this.root.mqJalaliBounds === 'function' ? (this.root.mqJalaliBounds() || {}) : {};
        if (Number.isFinite(extra.min) && (min === null || extra.min > min)) { min = extra.min; minLabel = extra.minLabel || ''; }
        if (Number.isFinite(extra.max) && (max === null || extra.max < max)) { max = extra.max; maxLabel = extra.maxLabel || ''; }
        if (this.dateOnly) { // a day is allowed when any part of it is
            if (min !== null) min = Math.floor(min / 1440) * 1440;
            if (max !== null) max = Math.floor(max / 1440) * 1440 + 1439;
        }
        return { min, max, minLabel, maxLabel };
    }

    // An empty field opens on another field's value (data-jalali-default-from="<name>", e.g. «آخرین زمان مجاز ورود»
    // opens on the exam's start), else on today at 00:00 — as {jy, jm, jd, hh, mm}; nothing is written until «تأیید».
    fallback() {
        const name = this.root.dataset.jalaliDefaultFrom;
        const source = name ? this.root.closest('form, body')?.querySelector(`[name="${name}"]`) : null;
        const from = source?.value ? wallParts(source.value) : null;
        const base = from || { ...tehranParts(), hh: 0, mm: 0 };
        const j = toJalaali(base.gy, base.gm, base.gd);
        return { jy: j.jy, jm: j.jm, jd: j.jd, hh: base.hh, mm: base.mm };
    }

    // `value` moved to the nearest allowed minute; unchanged when nothing is allowed.
    snap(value) {
        const { min, max } = this.bounds();
        if (min !== null && max !== null && min > max) return value;
        let minute = jalaliMinute(value);
        if (min !== null && minute < min) minute = min;
        if (max !== null && minute > max) minute = max;
        return minuteJalali(minute);
    }

    clear() {
        this.selected = null;
        this.display.value = '';
        this.hidden.value = '';
        this.hidden.dispatchEvent(new Event('change', { bubbles: true }));
        this.close();
    }

    open() {
        if (this.popup || this.display.disabled) return;
        addStyles();
        // a saved value is shown as it is (even outside today's range); a new one starts at the first allowed time
        this.draft = this.selected ? { ...this.selected } : this.snap(this.fallback());
        this.error = '';
        this.viewJy = this.draft.jy;
        this.viewJm = this.draft.jm;
        this.popup = document.createElement('div');
        this.popup.className = 'jalali-popup';
        this.popup.setAttribute('role', 'dialog');
        this.popup.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') { this.close(); this.display.focus(); }
        });
        // the field usually sits in a <label>: a click on the calendar's text would "click" the display box and close it
        this.popup.addEventListener('click', (event) => {
            if (!event.target.closest('button, select, option')) event.preventDefault();
        });
        this.root.appendChild(this.popup);
        this.render();
        // keep it on screen when the box is narrower than the calendar (phones down to 240px): one read, one write
        const box = this.popup.getBoundingClientRect();
        const gap = 8;
        if (box.left < gap) this.popup.style.right = `${box.left - gap}px`;
        else if (box.right > window.innerWidth - gap) this.popup.style.right = `${box.right - (window.innerWidth - gap)}px`;
    }

    close() {
        if (!this.popup) return;
        this.popup.remove();
        this.popup = null;
        this.draft = null;
        this.error = '';
    }

    changeMonth(delta) {
        let jm = this.viewJm + delta;
        let jy = this.viewJy;
        if (jm < 1) {
            jm = 12;
            jy -= 1;
        } else if (jm > 12) {
            jm = 1;
            jy += 1;
        }
        this.viewJy = jy;
        this.viewJm = jm;
        this.render();
    }

    format(minute) {
        return this.dateOnly ? formatWallMinute(minute).split(' - ')[0] : formatWallMinute(minute);
    }

    render() {
        const { min, max, minLabel, maxLabel } = this.bounds();
        const empty = min !== null && max !== null && min > max;
        const before = (minute) => min !== null && minute < min; // whole span ends before the range
        const after = (minute) => max !== null && minute > max;  // whole span starts after the range
        const monthLen = jalaaliMonthLength(this.viewJy, this.viewJm);
        const g1 = toGregorian(this.viewJy, this.viewJm, 1);
        const startWeekday = jalaaliWeekday(g1.gy, g1.gm, g1.gd);
        const monthStart = jalaliMinute({ jy: this.viewJy, jm: this.viewJm, jd: 1 });
        const prevBlocked = empty || before(monthStart - 1);
        const nextBlocked = empty || after(monthStart + monthLen * 1440);
        const draft = this.draft;
        const draftDay = jalaliMinute({ jy: draft.jy, jm: draft.jm, jd: draft.jd });

        let cells = '';
        for (let i = 0; i < startWeekday; i += 1) cells += '<span></span>';
        for (let day = 1; day <= monthLen; day += 1) {
            const dayStart = monthStart + (day - 1) * 1440;
            const off = empty || before(dayStart + 1439) || after(dayStart);
            const isSelected = draft.jy === this.viewJy && draft.jm === this.viewJm && draft.jd === day;
            cells += `<button type="button" class="jalali-day${isSelected ? ' is-selected' : ''}" data-day="${day}"`
                + `${off ? ' disabled' : ''} aria-pressed="${isSelected}">${toFaDigits(day)}</button>`;
        }

        // the shown value's own hour / minute stay selectable (a saved value outside the range is kept as it is)
        let hours = '';
        for (let h = 0; h < 24; h += 1) {
            const off = empty || before(draftDay + h * 60 + 59) || after(draftDay + h * 60);
            hours += `<option value="${h}"${h === draft.hh ? ' selected' : off ? ' disabled' : ''}>${toFaDigits(pad2(h))}</option>`;
        }
        let minutes = '';
        for (let m = 0; m < 60; m += 1) {
            const minute = draftDay + draft.hh * 60 + m;
            const off = empty || before(minute) || after(minute);
            minutes += `<option value="${m}"${m === draft.mm ? ' selected' : off ? ' disabled' : ''}>${toFaDigits(pad2(m))}</option>`;
        }

        let note = '';
        if (empty) {
            note = 'با زمان‌های دیگرِ این فرم هیچ زمانی برای این خانه مجاز نیست؛ ابتدا آن‌ها را اصلاح کنید.';
        } else if (min !== null || max !== null) {
            const from = min !== null ? `از ${this.format(min)}${minLabel ? ` (${minLabel})` : ''}` : '';
            const to = max !== null ? `تا ${this.format(max)}${maxLabel ? ` (${maxLabel})` : ''}` : '';
            note = `قابل انتخاب: ${[from, to].filter(Boolean).join(' ')}`;
        }
        if (!this.dateOnly) note += `${note ? '؛ ' : ''}ساعت به وقت ایران (تهران) است.`;

        this.popup.innerHTML = `
            <div class="jalali-popup-head">
                <button type="button" data-nav="next" aria-label="ماه بعد"${nextBlocked ? ' disabled' : ''}><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg></button>
                <strong>${MONTHS[this.viewJm - 1]} ${toFaDigits(this.viewJy)}</strong>
                <button type="button" data-nav="prev" aria-label="ماه قبل"${prevBlocked ? ' disabled' : ''}><svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg></button>
            </div>
            <div class="jalali-weekdays">${WEEKDAYS.map((w) => `<span>${w}</span>`).join('')}</div>
            <div class="jalali-grid">${cells}</div>
            <div class="jalali-time-row"${this.dateOnly ? ' hidden' : ''}>
                <label>ساعت<select data-hour>${hours}</select></label>
                <label>دقیقه<select data-minute>${minutes}</select></label>
            </div>
            ${note ? `<p class="jalali-range-note">${note}</p>` : ''}
            <p class="mq-rule-msg" role="alert" data-jalali-error${this.error ? '' : ' hidden'}></p>
            <button type="button" class="jalali-confirm" data-confirm>تأیید</button>
            ${this.hidden.required || !this.hidden.value ? '' : '<button type="button" class="jalali-confirm" data-clear style="margin-top:.4rem;background:#fff;color:#4b46ff;border:1px solid #d7dfea">پاک کردن</button>'}
        `;
        this.popup.querySelector('[data-jalali-error]').textContent = this.error;
        this.popup.querySelector('[data-clear]')?.addEventListener('click', () => this.clear());
        this.popup.querySelector('[data-nav="next"]').addEventListener('click', () => this.changeMonth(1));
        this.popup.querySelector('[data-nav="prev"]').addEventListener('click', () => this.changeMonth(-1));
        this.popup.querySelectorAll('.jalali-day:not(:disabled)').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.draft = this.snap({ ...this.draft, jy: this.viewJy, jm: this.viewJm, jd: Number(btn.dataset.day) });
                this.viewJy = this.draft.jy;
                this.viewJm = this.draft.jm;
                this.error = '';
                this.render();
                this.popup.querySelector(`.jalali-day[data-day="${this.draft.jd}"]`)?.focus();
            });
        });
        this.popup.querySelector('[data-hour]').addEventListener('change', (event) => {
            this.draft = this.snap({ ...this.draft, hh: clamp(Number(event.target.value), 0, 23) });
            this.viewJy = this.draft.jy;
            this.viewJm = this.draft.jm;
            this.error = '';
            this.render();
            this.popup.querySelector('[data-hour]').focus();
        });
        this.popup.querySelector('[data-minute]').addEventListener('change', (event) => {
            this.draft = { ...this.draft, mm: clamp(Number(event.target.value), 0, 59) };
            this.error = '';
            this.render();
            this.popup.querySelector('[data-minute]').focus();
        });
        this.popup.querySelector('[data-confirm]').addEventListener('click', () => this.confirm());
    }

    confirm() {
        const { min, max, minLabel, maxLabel } = this.bounds();
        const value = this.dateOnly ? { ...this.draft, hh: 0, mm: 0 } : this.draft;
        const minute = jalaliMinute(value);
        const unchanged = this.selected && this.hidden.value && jalaliMinute(this.selected) === jalaliMinute(this.draft);
        if (!unchanged) {
            let error = '';
            if (min !== null && max !== null && min > max) error = 'برای این خانه هیچ زمانی مجاز نیست؛ ابتدا زمان‌های دیگر را اصلاح کنید.';
            else if (min !== null && minute < min) error = `این زمان مجاز نیست؛ زمانی از ${this.format(min)}${minLabel ? ` (${minLabel})` : ''} به بعد انتخاب کنید.`;
            else if (max !== null && minute > max) error = `این زمان مجاز نیست؛ زمانی تا ${this.format(max)}${maxLabel ? ` (${maxLabel})` : ''} انتخاب کنید.`;
            if (error) {
                this.error = error;
                this.render();
                this.popup.querySelector('[data-confirm]').focus();
                return;
            }
        }
        this.selected = { ...this.draft };
        this.updateDisplay();
        this.close();
        this.display.focus();
    }
}

function init() {
    document.querySelectorAll('[data-jalali-field]').forEach((root) => {
        if (!root.dataset.jalaliInitialized) {
            root.dataset.jalaliInitialized = 'true';
            new JalaliDateTimeField(root);
        }
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
// date fields inside parts of the page swapped in by live-region.js
document.addEventListener('mq:live-load', init);
