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
    const jsDay = new Date(gy, gm - 1, gd).getDay();
    return (jsDay + 1) % 7;
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
        this.selected = null;

        this.display.addEventListener('click', () => this.toggle());
        document.addEventListener('click', (event) => {
            if (this.popup && !event.composedPath().includes(this.root)) this.close();
        });

        if (this.hidden.value) this.setFromIso(this.hidden.value);
    }

    setFromIso(iso) {
        const d = this.dateOnly ? new Date(`${iso.slice(0, 10)}T00:00`) : new Date(iso);
        if (Number.isNaN(d.getTime())) return;
        const j = toJalaali(d.getFullYear(), d.getMonth() + 1, d.getDate());
        this.selected = { jy: j.jy, jm: j.jm, jd: j.jd, hh: d.getHours(), mm: d.getMinutes() };
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

    open() {
        if (this.popup) return;
        const now = new Date();
        const nowJ = toJalaali(now.getFullYear(), now.getMonth() + 1, now.getDate());
        this.viewJy = this.selected ? this.selected.jy : nowJ.jy;
        this.viewJm = this.selected ? this.selected.jm : nowJ.jm;
        this.popup = document.createElement('div');
        this.popup.className = 'jalali-popup';
        this.root.appendChild(this.popup);
        this.render();
    }

    close() {
        if (!this.popup) return;
        this.popup.remove();
        this.popup = null;
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

    render() {
        const monthLen = jalaaliMonthLength(this.viewJy, this.viewJm);
        const g1 = toGregorian(this.viewJy, this.viewJm, 1);
        const startWeekday = jalaaliWeekday(g1.gy, g1.gm, g1.gd);
        const hh = this.selected ? this.selected.hh : 0;
        const mm = this.selected ? this.selected.mm : 0;

        let cells = '';
        for (let i = 0; i < startWeekday; i += 1) cells += '<span></span>';
        for (let day = 1; day <= monthLen; day += 1) {
            const isSelected = this.selected
                && this.selected.jy === this.viewJy
                && this.selected.jm === this.viewJm
                && this.selected.jd === day;
            cells += `<button type="button" class="jalali-day${isSelected ? ' is-selected' : ''}" data-day="${day}">${toFaDigits(day)}</button>`;
        }

        this.popup.innerHTML = `
            <div class="jalali-popup-head">
                <button type="button" data-nav="next" aria-label="ماه بعد"><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg></button>
                <strong>${MONTHS[this.viewJm - 1]} ${toFaDigits(this.viewJy)}</strong>
                <button type="button" data-nav="prev" aria-label="ماه قبل"><svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg></button>
            </div>
            <div class="jalali-weekdays">${WEEKDAYS.map((w) => `<span>${w}</span>`).join('')}</div>
            <div class="jalali-grid">${cells}</div>
            <div class="jalali-time-row"${this.dateOnly ? ' hidden' : ''}>
                <label>ساعت<input type="number" min="0" max="23" value="${pad2(hh)}" data-hour></label>
                <label>دقیقه<input type="number" min="0" max="59" value="${pad2(mm)}" data-minute></label>
            </div>
            <button type="button" class="jalali-confirm" data-confirm>تأیید</button>
        `;

        this.popup.querySelector('[data-nav="next"]').addEventListener('click', () => this.changeMonth(1));
        this.popup.querySelector('[data-nav="prev"]').addEventListener('click', () => this.changeMonth(-1));
        this.popup.querySelectorAll('.jalali-day').forEach((btn) => {
            btn.addEventListener('click', () => {
                const day = Number(btn.dataset.day);
                const hourInput = this.popup.querySelector('[data-hour]');
                const minuteInput = this.popup.querySelector('[data-minute]');
                this.selected = {
                    jy: this.viewJy,
                    jm: this.viewJm,
                    jd: day,
                    hh: clamp(Number(hourInput.value), 0, 23),
                    mm: clamp(Number(minuteInput.value), 0, 59),
                };
                this.render();
            });
        });
        this.popup.querySelector('[data-confirm]').addEventListener('click', () => {
            if (!this.selected) {
                this.selected = { jy: this.viewJy, jm: this.viewJm, jd: 1, hh: 0, mm: 0 };
            }
            const hourInput = this.popup.querySelector('[data-hour]');
            const minuteInput = this.popup.querySelector('[data-minute]');
            this.selected.hh = clamp(Number(hourInput.value), 0, 23);
            this.selected.mm = clamp(Number(minuteInput.value), 0, 59);
            this.updateDisplay();
            this.close();
        });
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
