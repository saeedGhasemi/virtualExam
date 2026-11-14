/* Persian file picker (templates/partials/file_picker.html + css/file-picker.css).
 *
 * The real <input type="file"> stays in the form, transparent and stretched over the whole drop zone, so clicking,
 * dropping a file on it, the keyboard (Tab, then Enter/Space) and the browser's `required` / `accept` checks all work
 * natively. This script only writes what was chosen («انتخاب نشده» / the file name / «۳ فایل: …») into
 * [data-file-picker-name] and marks the zone while a file is dragged over it. Everything is delegated from document,
 * so pickers inside live regions or added later work without set-up. Usage:
 *   {% include "partials/file_picker.html" with name="import_file" label="…" accept=".docx" required=True %}
 * plus, once per page, css/file-picker.css and this script.
 */
(() => {
  if (window.mqFilePicker) return;

  const pickerOf = (node) => node && node.closest && node.closest('[data-file-picker]');
  const inputOf = (picker) => picker.querySelector('input[type="file"]');

  const fa = (number) => number.toLocaleString('fa-IR', { maximumFractionDigits: 1 });
  const sizeText = (bytes) => {
    if (bytes >= 1024 * 1024) return `${fa(bytes / 1024 / 1024)} مگابایت`;
    return `${fa(Math.max(1, Math.round(bytes / 1024)))} کیلوبایت`;
  };

  const render = (picker) => {
    const input = inputOf(picker);
    const out = picker.querySelector('[data-file-picker-name]');
    if (!input || !out) return;
    const files = Array.from(input.files || []);
    picker.classList.toggle('has-file', files.length > 0);
    if (!files.length) {
      out.textContent = out.dataset.empty || 'فایلی انتخاب نشده است';
      out.removeAttribute('title');
      return;
    }
    const names = files.map((file) => file.name);
    out.textContent = files.length === 1
      ? `${names[0]} (${sizeText(files[0].size)})`
      : `${fa(files.length)} فایل: ${names.join('، ')}`;
    out.title = names.join('\n');
  };

  document.addEventListener('change', (event) => {
    const picker = pickerOf(event.target);
    if (picker && event.target.type === 'file') render(picker);
  });
  document.addEventListener('reset', (event) => {
    // the form clears its inputs after this event: read them once it has
    event.target.querySelectorAll?.('[data-file-picker]').forEach((picker) => queueMicrotask(() => render(picker)));
  }, true);
  ['dragenter', 'dragover'].forEach((type) => document.addEventListener(type, (event) => {
    const picker = pickerOf(event.target);
    if (picker) picker.classList.add('is-dragover');
  }));
  ['dragleave', 'drop'].forEach((type) => document.addEventListener(type, (event) => {
    const picker = pickerOf(event.target);
    if (picker) picker.classList.remove('is-dragover');
  }));
  // Back/forward cache or a re-rendered form can bring files back without a change event.
  const renderAll = () => document.querySelectorAll('[data-file-picker]').forEach(render);
  window.addEventListener('pageshow', renderAll);
  document.addEventListener('mq:live-load', renderAll);

  window.mqFilePicker = { render };
})();
