/*
 * Question builder: numeric, matrix, image-labelling and audio/video question types.
 * Loaded by templates/teacher/_question_form.html next to its inline script. Matrix rows/columns and image markers
 * are kept here and written to the hidden matrix_json / label_markers_json fields on every change (so the inline
 * script's autosave and submit see them). renderPreview() builds the student-preview answer area with the same
 * markup as templates/student/attempt.html and the shared static/js/exam-interactions.js behaviours.
 */
(() => {
  const form = document.querySelector('[data-question-create-form]');
  if (!form) return;
  const toFa = (value) => String(value).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]).replace(/\./g, '٫');
  const toEn = (value) => String(value ?? '').replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/٫/g, '.').trim();
  const num = (value, fallback = 0) => { const n = Number(toEn(value)); return Number.isFinite(n) && toEn(value) !== '' ? n : fallback; };
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const changed = (input) => input.dispatchEvent(new Event('change', { bubbles: true }));
  const readJson = (id, fallback) => { try { return JSON.parse(document.getElementById(id)?.textContent || '') ?? fallback; } catch (error) { return fallback; } };
  let uid = 0;
  const newId = (prefix) => `${prefix}n${Date.now().toString(36)}${(uid += 1)}`;

  // ----- numeric: live «محدوده قابل قبول» -----
  const numericCard = form.querySelector('[data-v2-numeric]');
  const numericRange = () => {
    const q = (selector) => numericCard.querySelector(selector);
    const value = toEn(q('[data-num-value]').value);
    const mode = form.querySelector('[data-num-mode]:checked')?.value || 'absolute';
    const tolerance = Math.abs(num(q('[data-num-tolerance]').value));
    const decimals = Number(q('[data-num-decimals]').value || 0);
    const unit = q('[data-num-unit]').value.trim();
    q('[data-num-tolerance-sign]').textContent = mode === 'percent' ? '%' : '±';
    const out = q('[data-num-range]');
    if (value === '' || !Number.isFinite(Number(value))) { out.textContent = ''; return; }
    const center = Number(value);
    const delta = mode === 'percent' ? Math.abs(center) * tolerance / 100 : tolerance;
    const fixed = (n) => toFa(n.toFixed(decimals));
    const suffix = unit ? ` ${unit}` : '';
    out.textContent = delta
      ? `محدوده قابل قبول: ${fixed(center - delta)} تا ${fixed(center + delta)}${suffix} (${mode === 'percent' ? `±${toFa(tolerance)}٪` : `±${toFa(tolerance)}${suffix}`})`
      : `فقط پاسخ دقیق ${fixed(center)}${suffix} پذیرفته می‌شود.`;
  };
  if (numericCard) {
    numericCard.addEventListener('input', numericRange);
    numericCard.addEventListener('change', numericRange);
    numericRange();
  }

  // ----- matrix editor -----
  const matrixCard = form.querySelector('[data-v2-matrix]');
  const matrix = readJson('matrix-data', { columns: [], rows: [] });
  const matrixMulti = () => form.querySelector('[data-matrix-selection]:checked')?.value === 'multi';
  const syncMatrix = () => {
    const hidden = form.querySelector('[data-matrix-json]');
    hidden.value = JSON.stringify(matrix);
    changed(hidden);
  };
  const pointsSelect = (value, onChange) => {
    const select = el('select');
    select.setAttribute('aria-label', 'نمره سطر');
    ['0.5', '1', '1.5', '2', '3', '4', '5'].forEach((option) => select.append(new Option(toFa(option), option)));
    if (![...select.options].some((option) => Number(option.value) === Number(value))) select.append(new Option(toFa(value), String(value)));
    select.value = [...select.options].find((option) => Number(option.value) === Number(value))?.value || '1';
    select.addEventListener('change', () => onChange(Number(select.value)));
    return select;
  };
  const iconButton = (title, text, onClick) => {
    const button = el('button', 'qb-icon-btn', text);
    button.type = 'button';
    button.title = title;
    button.setAttribute('aria-label', title);
    button.addEventListener('click', onClick);
    return button;
  };
  const renderMatrix = () => {
    const table = form.querySelector('[data-matrix-table]');
    table.innerHTML = '';
    const multi = matrixMulti();
    const head = el('tr');
    head.append(el('th', '', 'گزینه‌ها / سطرها'));
    matrix.columns.forEach((column, index) => {
      const th = el('th');
      const box = el('div', 'qb2-col');
      const input = el('input');
      input.type = 'text';
      input.value = column.text || '';
      input.placeholder = `ستون ${toFa(index + 1)}`;
      input.maxLength = 300;
      input.addEventListener('input', () => { column.text = input.value; syncMatrix(); });
      box.append(input);
      if (matrix.columns.length > 2) box.append(iconButton('حذف ستون', '×', () => {
        matrix.columns.splice(index, 1);
        matrix.rows.forEach((row) => { row.correct = row.correct.filter((id) => id !== column.id); });
        renderMatrix(); syncMatrix();
      }));
      th.append(box);
      head.append(th);
    });
    head.append(el('th', '', 'نمره هر سطر'), el('th'));
    const thead = el('thead');
    thead.append(head);
    const tbody = el('tbody');
    matrix.rows.forEach((row, rowIndex) => {
      const tr = el('tr');
      const label = el('td');
      const input = el('input');
      input.type = 'text';
      input.value = row.text || '';
      input.placeholder = `سطر ${toFa(rowIndex + 1)}`;
      input.maxLength = 300;
      input.addEventListener('input', () => { row.text = input.value; syncMatrix(); });
      label.append(input);
      tr.append(label);
      matrix.columns.forEach((column) => {
        const td = el('td');
        const mark = el('input');
        mark.type = multi ? 'checkbox' : 'radio';
        mark.name = `_matrix_correct_${row.id}`;
        mark.checked = row.correct.includes(column.id);
        mark.setAttribute('aria-label', `پاسخ صحیح: ${row.text || `سطر ${rowIndex + 1}`} — ${column.text || 'ستون'}`);
        mark.addEventListener('change', () => {
          if (multi) row.correct = mark.checked ? [...new Set([...row.correct, column.id])] : row.correct.filter((id) => id !== column.id);
          else row.correct = [column.id];
          syncMatrix();
        });
        td.append(mark);
        tr.append(td);
      });
      const points = el('td');
      points.append(pointsSelect(row.points ?? 1, (value) => { row.points = value; syncMatrix(); }));
      tr.append(points);
      const remove = el('td');
      if (matrix.rows.length > 1) remove.append(iconButton('حذف سطر', '×', () => { matrix.rows.splice(rowIndex, 1); renderMatrix(); syncMatrix(); }));
      tr.append(remove);
      tbody.append(tr);
    });
    table.append(thead, tbody);
  };
  if (matrixCard) {
    matrix.rows.forEach((row) => { row.correct = row.correct || []; });
    form.querySelector('[data-matrix-add-row]').addEventListener('click', () => {
      matrix.rows.push({ id: newId('r'), text: '', points: 1, correct: [] });
      renderMatrix(); syncMatrix();
      form.querySelector('[data-matrix-table] tbody tr:last-child input[type="text"]')?.focus();
    });
    form.querySelector('[data-matrix-add-column]').addEventListener('click', () => {
      if (matrix.columns.length >= 10) { alert('حداکثر ۱۰ ستون مجاز است.'); return; }
      matrix.columns.push({ id: newId('c'), text: '' });
      renderMatrix(); syncMatrix();
    });
    form.querySelectorAll('[data-matrix-selection]').forEach((radio) => radio.addEventListener('change', () => {
      // Switching to single choice keeps only the first correct column of each row.
      if (!matrixMulti()) matrix.rows.forEach((row) => { row.correct = row.correct.slice(0, 1); });
      renderMatrix(); syncMatrix();
    }));
    renderMatrix();
    syncMatrix();
  }

  // ----- image labelling editor -----
  const labelCard = form.querySelector('[data-v2-label]');
  const markers = (readJson('label-markers', []) || []).map((item) => ({
    x: Number(item.x) || 50, y: Number(item.y) || 50, answer: item.answer || '', synonyms: item.synonyms || '', points: Number(item.points) || 1,
  }));
  let selected = -1;
  let tool = 'add';
  const syncLabels = () => {
    const hidden = form.querySelector('[data-label-json]');
    hidden.value = JSON.stringify(markers.map((item) => ({ ...item, x: Math.round(item.x * 100) / 100, y: Math.round(item.y * 100) / 100 })));
    changed(hidden);
  };
  const stemImage = () => {
    const slot = form.querySelector('[data-media-panel="image"] [data-media-slot]');
    return slot?.classList.contains('has-media') ? slot.querySelector('[data-media-preview] img')?.src || '' : '';
  };
  const renderLabels = () => {
    const canvas = form.querySelector('[data-label-canvas]');
    const image = canvas.querySelector('[data-label-image]');
    const src = stemImage();
    if (src && image.src !== src) image.src = src;
    image.hidden = !src;
    canvas.querySelector('[data-label-empty]').hidden = !!src;
    canvas.classList.toggle('is-move', tool === 'move');
    canvas.querySelectorAll('.qb2-pin').forEach((pin) => pin.remove());
    if (src) markers.forEach((item, index) => {
      const pin = el('button', `qb2-pin${index === selected ? ' is-selected' : ''}`, toFa(index + 1));
      pin.type = 'button';
      pin.style.left = `${item.x}%`;
      pin.style.top = `${item.y}%`;
      pin.style.transform = 'translate(-50%,-50%)';
      pin.dataset.index = String(index);
      pin.setAttribute('aria-label', `نشانه ${index + 1}`);
      canvas.append(pin);
    });
    const tbody = form.querySelector('[data-label-rows]');
    tbody.innerHTML = '';
    markers.forEach((item, index) => {
      const tr = el('tr', index === selected ? 'is-selected' : '');
      tr.addEventListener('focusin', () => { if (selected !== index) { selected = index; highlight(); } });
      const numberCell = el('td');
      numberCell.append(el('span', 'qb2-num', toFa(index + 1)));
      const field = (key, placeholder, maxLength) => {
        const td = el('td');
        const input = el('input');
        input.type = 'text';
        input.value = item[key];
        input.placeholder = placeholder;
        input.maxLength = maxLength;
        input.addEventListener('input', () => { item[key] = input.value; syncLabels(); });
        td.append(input);
        return td;
      };
      const points = el('td');
      points.append(pointsSelect(item.points, (value) => { item.points = value; syncLabels(); }));
      const remove = el('td');
      remove.append(iconButton('حذف نشانه', '×', () => removeMarker(index)));
      tr.append(numberCell, field('answer', 'مثلاً آئورت', 120), field('synonyms', 'با ویرگول جدا کنید', 600), points, remove);
      tbody.append(tr);
    });
    form.querySelector('[data-label-empty-rows]').hidden = markers.length > 0;
  };
  const highlight = () => {
    form.querySelectorAll('.qb2-pin').forEach((pin) => pin.classList.toggle('is-selected', Number(pin.dataset.index) === selected));
    form.querySelectorAll('[data-label-rows] tr').forEach((tr, index) => tr.classList.toggle('is-selected', index === selected));
  };
  const removeMarker = (index) => {
    if (index < 0 || index >= markers.length) return;
    markers.splice(index, 1);
    selected = -1;
    renderLabels(); syncLabels();
  };
  const pointerPercent = (event, image) => {
    const rect = image.getBoundingClientRect();
    return {
      x: Math.min(Math.max(((event.clientX - rect.left) / rect.width) * 100, 0), 100),
      y: Math.min(Math.max(((event.clientY - rect.top) / rect.height) * 100, 0), 100),
    };
  };
  if (labelCard) {
    const canvas = form.querySelector('[data-label-canvas]');
    const image = canvas.querySelector('[data-label-image]');
    let dragging = -1;
    canvas.addEventListener('pointerdown', (event) => {
      const pin = event.target.closest('.qb2-pin');
      if (pin) {
        selected = Number(pin.dataset.index);
        highlight();
        if (tool === 'move') { dragging = selected; pin.setPointerCapture(event.pointerId); event.preventDefault(); }
        return;
      }
      if (event.target !== image || tool !== 'add') return;
      if (markers.length >= 30) { alert('حداکثر ۳۰ نشانه مجاز است.'); return; }
      markers.push({ ...pointerPercent(event, image), answer: '', synonyms: '', points: 1 });
      selected = markers.length - 1;
      renderLabels(); syncLabels();
      // No scroll: the teacher usually places several markers in a row.
      form.querySelectorAll('[data-label-rows] tr')[selected]?.querySelector('input')?.focus({ preventScroll: true });
    });
    canvas.addEventListener('pointermove', (event) => {
      if (dragging < 0) return;
      Object.assign(markers[dragging], pointerPercent(event, image));
      const pin = canvas.querySelector(`.qb2-pin[data-index="${dragging}"]`);
      pin.style.left = `${markers[dragging].x}%`;
      pin.style.top = `${markers[dragging].y}%`;
    });
    const endDrag = () => { if (dragging >= 0) { dragging = -1; syncLabels(); } };
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);
    form.querySelectorAll('[data-label-tool]').forEach((button) => button.addEventListener('click', () => {
      tool = button.dataset.labelTool;
      form.querySelectorAll('[data-label-tool]').forEach((other) => {
        other.classList.toggle('is-active', other === button);
        other.setAttribute('aria-pressed', String(other === button));
      });
      canvas.classList.toggle('is-move', tool === 'move');
    }));
    form.querySelector('[data-label-delete]').addEventListener('click', () => {
      if (selected < 0) { alert('ابتدا یک نشانه را انتخاب کنید.'); return; }
      removeMarker(selected);
    });
    form.querySelector('[data-label-open-image]').addEventListener('click', () => {
      form.querySelector('[data-media-tab="image"]')?.click();
      form.querySelector('[data-media-panel="image"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    // The labelled image is the stem image: follow its slot (pick, replace, delete) live.
    const imagePanel = form.querySelector('[data-media-panel="image"]');
    if (imagePanel) new MutationObserver(renderLabels).observe(imagePanel, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'src'] });
    renderLabels();
    syncLabels();
  }

  // ----- audio/video question: rubric rows, attachment preview -----
  const rubricCard = form.querySelector('[data-media-rubric]');
  const refreshMediaRubric = () => {
    const total = [...form.querySelectorAll('[data-media-rubric-points]')].reduce((sum, input) => sum + num(input.value), 0);
    form.querySelector('[data-media-rubric-total]').textContent = toFa(Math.round(total * 100) / 100);
  };
  if (rubricCard) {
    const rows = rubricCard.querySelector('[data-media-rubric-rows]');
    rubricCard.addEventListener('input', refreshMediaRubric);
    rubricCard.querySelector('[data-media-rubric-add]').addEventListener('click', () => {
      const clone = rows.lastElementChild.cloneNode(true);
      clone.querySelectorAll('input').forEach((input) => { input.value = ''; });
      rows.append(clone);
      clone.querySelector('input').focus();
    });
    rubricCard.addEventListener('click', (event) => {
      const button = event.target.closest('[data-media-rubric-remove]');
      if (!button) return;
      const row = button.closest('tr');
      if (rows.children.length > 1) row.remove();
      else row.querySelectorAll('input').forEach((input) => { input.value = ''; });
      refreshMediaRubric();
      changed(rows.querySelector('input'));
    });
    refreshMediaRubric();
    const replay = form.querySelector('[data-media-replay]');
    const maxPlays = form.querySelector('[data-media-max-plays]');
    const syncReplay = () => { maxPlays.disabled = !replay.checked; };
    replay.addEventListener('change', syncReplay);
    syncReplay();
  }
  const attachInput = form.querySelector('[data-attach-file]');
  if (attachInput) attachInput.addEventListener('change', () => {
    const box = form.querySelector('[data-attach-preview]');
    box.querySelectorAll('img').forEach((img) => URL.revokeObjectURL(img.src));
    box.innerHTML = '';
    const file = attachInput.files[0];
    box.hidden = !file;
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) { alert('حجم فایل مکمل بیش از ۱۰ مگابایت است.'); attachInput.value = ''; box.hidden = true; return; }
    if (file.type.startsWith('image/')) {
      const img = el('img');
      img.alt = '';
      img.src = URL.createObjectURL(file);
      box.append(img);
    }
    box.append(el('span', '', `${file.name} — ${toFa(Math.max(1, Math.round(file.size / 1024)))} کیلوبایت`));
  });

  // ----- student preview (mirrors templates/student/attempt.html) -----
  const answerHeading = (area) => area.append(el('h3', '', 'پاسخ شما'));
  const previewRenderers = {
    numeric(area) {
      answerHeading(area);
      const box = el('div', 'qx-numeric');
      const input = el('input', 'qx-input');
      input.inputMode = 'decimal';
      input.placeholder = 'پاسخ خود را وارد کنید';
      box.append(input);
      const unit = form.querySelector('[data-num-unit]')?.value.trim();
      if (form.querySelector('[name="numeric_require_unit"]')?.checked) {
        const unitInput = el('input', 'qx-input qx-numeric-unit');
        unitInput.placeholder = 'واحد';
        box.append(unitInput);
      } else if (unit) box.append(el('span', 'qx-numeric-unit', unit));
      area.append(box);
    },
    matrix(area) {
      const multi = matrixMulti();
      const showColumns = form.querySelector('[name="matrix_show_column_titles"]')?.checked;
      const showRows = form.querySelector('[name="matrix_show_row_titles"]')?.checked;
      const wrap = el('div', 'qx-matrix-wrap');
      const table = el('table', 'qx-matrix');
      table.dataset.matrix = '';
      if (showColumns) {
        const head = el('tr');
        head.append(el('th'));
        matrix.columns.forEach((column) => head.append(el('th', '', column.text)));
        const thead = el('thead');
        thead.append(head);
        table.append(thead);
      }
      const tbody = el('tbody');
      matrix.rows.forEach((row, index) => {
        const tr = el('tr');
        const th = el('th', '', showRows ? row.text : toFa(index + 1));
        th.scope = 'row';
        tr.append(th);
        matrix.columns.forEach((column, columnIndex) => {
          const td = el('td');
          const input = el('input');
          input.type = multi ? 'checkbox' : 'radio';
          input.name = `preview_mx_${row.id}`;
          input.value = `${row.id}:${column.id}`;
          input.dataset.matrixCell = '';
          input.setAttribute('aria-label', `${row.text} — ${column.text || toFa(columnIndex + 1)}`);
          td.append(input);
          tr.append(td);
        });
        tbody.append(tr);
      });
      table.append(tbody);
      wrap.append(table);
      const answer = el('input');
      answer.type = 'hidden';
      area.append(wrap, answer);
      window.ExamInteractions.matrix(table, answer);
    },
    image_label(area) {
      const src = stemImage();
      if (!src) { area.append(el('p', 'qx-select-hint', 'تصویر سؤال هنوز بارگذاری نشده است.')); return; }
      const drag = form.querySelector('[name="label_answer_mode"]:checked')?.value === 'drag';
      const root = el('div', 'qx-label');
      root.dataset.label = '';
      if (drag) root.dataset.labelDrag = '';
      const stage = el('div', 'qx-label-stage');
      const image = el('img');
      image.src = src;
      image.alt = form.querySelector('[name="question_image_alt"]')?.value.trim() || '';
      stage.append(image);
      markers.forEach((item, index) => {
        const pin = el('span', 'qx-label-pin', toFa(index + 1));
        pin.style.left = `${item.x}%`;
        pin.style.top = `${item.y}%`;
        stage.append(pin);
      });
      root.append(stage);
      if (drag) {
        const bank = el('div', 'qx-label-bank');
        bank.dataset.labelBank = '';
        markers.map((item) => item.answer.trim()).filter(Boolean).sort(() => Math.random() - 0.5).forEach((text) => {
          const chip = el('button', 'qx-label-chip', text);
          chip.type = 'button';
          chip.draggable = true;
          chip.dataset.labelChip = '';
          bank.append(chip);
        });
        root.append(bank);
      }
      const list = el('ol', 'qx-label-answers');
      markers.forEach((item, index) => {
        const li = el('li');
        const input = el('input', 'qx-input');
        input.type = 'text';
        input.dataset.labelInput = '';
        input.setAttribute('aria-label', `پاسخ نشانه ${index + 1}`);
        input.placeholder = drag ? 'برچسب را اینجا رها کنید' : 'نام بخش';
        input.readOnly = drag;
        li.append(el('b', '', toFa(index + 1)), input);
        if (drag) {
          const clear = el('button', 'qx-label-clear', '×');
          clear.type = 'button';
          clear.dataset.labelClear = '';
          clear.setAttribute('aria-label', 'پاک کردن');
          li.append(clear);
        }
        list.append(li);
      });
      root.append(list);
      area.append(root);
      window.ExamInteractions.imageLabel(root);
    },
    media_response(area) {
      answerHeading(area);
      const formats = [...form.querySelectorAll('[name="answer_formats"]:checked')].map((input) => input.value);
      if (formats.includes('text')) {
        const textarea = el('textarea', 'qx-textarea');
        textarea.placeholder = 'پاسخ خود را بنویسید...';
        area.append(textarea);
      }
      const actions = el('div', 'qx-upload-actions');
      const seconds = num(form.querySelector('[name="media_max_record_seconds"]')?.value, 120);
      [['audio', '● ضبط صدا'], ['video', '● ضبط ویدئو']].forEach(([kind, label]) => {
        if (!formats.includes(kind)) return;
        const button = el('button', 'qx-upload-btn', label);
        button.type = 'button';
        button.disabled = true;
        button.title = 'در پیش‌نمایش ضبط نمی‌شود';
        actions.append(button);
      });
      if (actions.children.length) {
        const box = el('div', 'qx-uploads');
        box.append(actions, el('small', 'qx-upload-hint', `حداکثر زمان ضبط: ${toFa(seconds)} ثانیه؛ فایل بلافاصله پس از پایان ضبط ذخیره می‌شود.`));
        area.append(box);
      }
      const plays = form.querySelector('[data-media-replay]')?.checked ? num(form.querySelector('[data-media-max-plays]')?.value, 0) : 1;
      const clock = (value) => { const parts = toEn(value).split(':'); return value.trim() ? Number(parts.at(-2) || 0) * 60 + Number(parts.at(-1) || 0) : null; };
      document.querySelectorAll('[data-qx-media] audio, [data-qx-media] video').forEach((media) => window.ExamInteractions.playback(media, {
        maxPlays: plays,
        start: clock(form.querySelector('[name="media_range_start"]')?.value || ''),
        end: clock(form.querySelector('[name="media_range_end"]')?.value || ''),
      }));
      if (plays) area.prepend(el('p', 'qx-select-hint', `فایل سؤال حداکثر ${toFa(plays)} بار قابل پخش است.`));
      const transcript = form.querySelector('[name="media_transcript"]')?.value.trim();
      if (transcript && form.querySelector('[name="media_show_transcript"]')?.checked) {
        const details = el('details', 'qx-transcript');
        details.append(el('summary', '', 'متن رونویسی'), el('p', '', transcript));
        area.prepend(details);
      }
    },
  };
  window.QuestionTypesV2 = {
    renderPreview(kind, area) { previewRenderers[kind]?.(area); },
  };
})();
