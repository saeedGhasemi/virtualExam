/* Panel top bar: «اعلان‌ها» (bell) and «جستجو» (magnifier) popovers (partials/super_admin_chrome.html).
   Server side: apps/core/panel_header.py (header comment).
   - Bell: the unread count is fetched in the background on load (badge on the bell); opening the popover lists the
     latest notifications; clicking one marks it read and follows its link; «همه خوانده شد» marks all read.
   - Search: the query is sent only on Enter / the «جستجو» button (user's rule: never while typing); results are links.
   Popovers close on Esc, on a click outside, and when the other one opens; focus returns to the button. */
(function () {
  var FA = '۰۱۲۳۴۵۶۷۸۹';
  function fa(n) { return String(n).replace(/\d/g, function (d) { return FA[d]; }); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }
  function when(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString('fa-IR-u-ca-persian', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch (e) { return ''; }
  }

  var open = null;
  function close(box, focusButton) {
    if (!box) return;
    var pop = box.querySelector('.mq-hd-pop'), btn = box.querySelector('.mq-hd-btn');
    pop.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    if (open === box) open = null;
    if (focusButton) btn.focus();
  }
  function show(box) {
    if (open && open !== box) close(open);
    box.querySelector('.mq-hd-pop').hidden = false;
    box.querySelector('.mq-hd-btn').setAttribute('aria-expanded', 'true');
    open = box;
  }
  document.addEventListener('click', function (e) { if (open && !open.contains(e.target)) close(open); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && open) close(open, true); });

  // ---- notifications ----
  function initNotify(box) {
    var url = box.dataset.url, list = box.querySelector('[data-hd-list]'), count = box.querySelector('[data-hd-count]');
    var readAll = box.querySelector('[data-hd-read-all]'), btn = box.querySelector('.mq-hd-btn');
    function paint(data) {
      var unread = data.unread || 0;
      count.hidden = !unread;
      count.textContent = unread > 99 ? '۹۹+' : fa(unread);
      btn.setAttribute('aria-label', unread ? 'اعلان‌ها — ' + fa(unread) + ' خوانده‌نشده' : 'اعلان‌ها');
      readAll.hidden = !unread;
      if (!data.items || !data.items.length) { list.innerHTML = '<p class="mq-hd-empty">اعلانی ندارید.</p>'; return; }
      list.innerHTML = data.items.map(function (item) {
        return '<button type="button" class="mq-hd-item' + (item.is_read ? '' : ' is-unread') + '" data-id="' + esc(item.id) +
          '" data-link="' + esc(item.link) + '"><b>' + esc(item.title) + '</b>' + (item.message ? '<span>' + esc(item.message) + '</span>' : '') +
          (item.at ? '<small>' + esc(when(item.at)) + '</small>' : '') + '</button>';
      }).join('');
    }
    function load(opts) {
      return fetch(url, Object.assign({ credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } }, opts || {}))
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(paint)
        .catch(function () { list.innerHTML = '<p class="mq-hd-empty">دریافت اعلان‌ها ممکن نشد؛ دوباره تلاش کنید.</p>'; });
    }
    function post(body, background) {
      var form = new FormData();
      Object.keys(body).forEach(function (k) { form.append(k, body[k]); });
      return load({ method: 'POST', body: form, headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' }, mqBackground: !!background });
    }
    load({ mqBackground: true });  // badge only; not a user action, so no loader
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (open === box) { close(box); return; }
      show(box);
      load({ mqBackground: true });
    });
    readAll.addEventListener('click', function () { post({ all: '1' }); });
    list.addEventListener('click', function (e) {
      var item = e.target.closest('.mq-hd-item');
      if (!item) return;
      var link = item.dataset.link;
      var done = post({ id: item.dataset.id }, !!link);
      if (link) done.then(function () { window.location.href = link; });
    });
  }

  // ---- search ----
  function initSearch(box) {
    var url = box.dataset.url, form = box.querySelector('[data-hd-search-form]'), input = form.querySelector('input');
    var results = box.querySelector('[data-hd-results]'), btn = box.querySelector('.mq-hd-btn');
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (open === box) { close(box); return; }
      show(box);
      input.focus();
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var q = input.value.trim();
      if (q.length < 2) { results.innerHTML = '<p class="mq-hd-empty">دست‌کم ۲ حرف بنویسید.</p>'; return; }
      results.innerHTML = '<p class="mq-hd-empty">در حال جستجو…</p>';
      fetch(url + '?q=' + encodeURIComponent(q), { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) {
          if (!data.groups || !data.groups.length) { results.innerHTML = '<p class="mq-hd-empty">' + esc(data.message || 'نتیجه‌ای پیدا نشد.') + '</p>'; return; }
          results.innerHTML = data.groups.map(function (group) {
            return '<p class="mq-hd-group">' + esc(group.label) + '</p>' + group.items.map(function (item) {
              return '<a class="mq-hd-item mq-hd-hit" href="' + esc(item.url) + '"><b>' + esc(item.title) + '</b><em>' + esc(item.hint) + '</em></a>';
            }).join('');
          }).join('');
        })
        .catch(function () { results.innerHTML = '<p class="mq-hd-empty">جستجو انجام نشد؛ دوباره تلاش کنید.</p>'; });
    });
  }

  function init() {
    document.querySelectorAll('[data-panel-notify]').forEach(function (box) { if (!box.__hd) { box.__hd = 1; initNotify(box); } });
    document.querySelectorAll('[data-panel-search]').forEach(function (box) { if (!box.__hd) { box.__hd = 1; initSearch(box); } });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
