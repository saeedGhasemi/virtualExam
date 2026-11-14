/*
 * Question builder: numeric, matrix, image-labelling, image-hotspot and audio/video question types.
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
    lx: item.lx === null || item.lx === undefined ? null : Number(item.lx), ly: item.ly === null || item.ly === undefined ? null : Number(item.ly),
  }));
  let selected = -1;
  let tool = 'add';
  const labelTexts = (readJson('label-texts', []) || []).map((item) => ({ x: Number(item.x) || 50, y: Number(item.y) || 50, text: item.text || '' }));
  let selectedText = -1;
  const syncTexts = () => {
    const hidden = form.querySelector('[data-label-texts-json]');
    if (!hidden) return;
    hidden.value = JSON.stringify(labelTexts.map((item) => ({ x: Math.round(item.x * 100) / 100, y: Math.round(item.y * 100) / 100, text: item.text })));
    changed(hidden);
  };
  const renderTextRows = () => {
    const rows = form.querySelector('[data-label-text-rows]');
    if (!rows) return;
    rows.innerHTML = '';
    labelTexts.forEach((item, index) => {
      const row = el('div', 'qb2-text-row');
      const input = el('input');
      input.type = 'text'; input.maxLength = 60; input.value = item.text; input.placeholder = 'چپ';
      input.addEventListener('input', () => {
        item.text = input.value;
        const node = form.querySelector(`.qb2-text[data-text-index="${index}"]`);
        if (node) node.textContent = item.text || '…';
        syncTexts();
      });
      row.append(el('span', 'qb2-num', toFa(index + 1)), input, iconButton('حذف متن', '×', () => { labelTexts.splice(index, 1); selectedText = -1; renderLabels(); syncTexts(); }));
      rows.append(row);
    });
    form.querySelector('[data-label-texts-empty]').hidden = labelTexts.length > 0;
  };
  const syncLabels = () => {
    const hidden = form.querySelector('[data-label-json]');
    const r2 = (value) => (value == null ? null : Math.round(value * 100) / 100);
    hidden.value = JSON.stringify(markers.map((item) => ({ ...item, x: r2(item.x), y: r2(item.y), lx: r2(item.lx), ly: r2(item.ly) })));
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
    canvas.classList.toggle('is-line', tool === 'line');
    canvas.querySelectorAll('.qb2-pin, .qb2-anchor, .qb2-label-lines, .qb2-text').forEach((node) => node.remove());
    canvas.classList.toggle('is-text', tool === 'text');
    if (src) labelTexts.forEach((item, index) => {
      const node = el('span', `qb2-text${index === selectedText ? ' is-selected' : ''}`, item.text || '…');
      node.dataset.textIndex = String(index);
      node.style.left = `${item.x}%`;
      node.style.top = `${item.y}%`;
      canvas.append(node);
    });
    renderTextRows();
    if (src) {
      const lines = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      lines.setAttribute('class', 'qb2-label-lines');
      lines.setAttribute('viewBox', '0 0 100 100');
      lines.setAttribute('preserveAspectRatio', 'none');
      canvas.append(lines);
    }
    if (src) markers.forEach((item, index) => {
      const pin = el('button', `qb2-pin${index === selected ? ' is-selected' : ''}`, toFa(index + 1));
      pin.type = 'button';
      pin.style.transform = 'translate(-50%,-50%)';
      pin.dataset.index = String(index);
      pin.setAttribute('aria-label', `نشانه ${index + 1}`);
      canvas.append(pin);
      placeMarker(index);
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
  // A marker's pin sits on its callout (lx, ly) when it has one, with a line and a dot at the labelled point.
  function placeMarker(index) {
    const canvas = form.querySelector('[data-label-canvas]');
    const item = markers[index];
    const pin = canvas.querySelector(`.qb2-pin[data-index="${index}"]`);
    if (!pin || !item) return;
    const callout = item.lx != null && item.ly != null;
    pin.style.left = `${callout ? item.lx : item.x}%`;
    pin.style.top = `${callout ? item.ly : item.y}%`;
    const lines = canvas.querySelector('.qb2-label-lines');
    let line = lines?.querySelector(`line[data-index="${index}"]`);
    let dot = canvas.querySelector(`.qb2-anchor[data-index="${index}"]`);
    if (!callout) { line?.remove(); dot?.remove(); return; }
    if (!line && lines) {
      line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.dataset.index = String(index);
      lines.append(line);
    }
    line?.setAttribute('x1', item.lx); line?.setAttribute('y1', item.ly); line?.setAttribute('x2', item.x); line?.setAttribute('y2', item.y);
    if (!dot) {
      dot = el('span', 'qb2-anchor');
      dot.dataset.index = String(index);
      canvas.append(dot);
    }
    dot.style.left = `${item.x}%`;
    dot.style.top = `${item.y}%`;
  }
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
    let dragCallout = false;
    let draggingText = -1;
    canvas.addEventListener('pointerdown', (event) => {
      const caption = event.target.closest('.qb2-text');
      if (caption) {
        selectedText = Number(caption.dataset.textIndex);
        form.querySelectorAll('.qb2-text').forEach((node) => node.classList.toggle('is-selected', node === caption));
        draggingText = selectedText;  // captions can be dragged with any tool
        caption.setPointerCapture(event.pointerId);
        event.preventDefault();
        return;
      }
      if (tool === 'text' && (event.target === image || event.target.closest('.qb2-label-lines'))) {
        if (labelTexts.length >= 20) { alert('حداکثر ۲۰ متن مجاز است.'); return; }
        labelTexts.push({ ...pointerPercent(event, image), text: '' });
        selectedText = labelTexts.length - 1;
        renderLabels(); syncTexts();
        form.querySelectorAll('[data-label-text-rows] input')[selectedText]?.focus({ preventScroll: true });
        return;
      }
      const pin = event.target.closest('.qb2-pin');
      if (pin) {
        selected = Number(pin.dataset.index);
        highlight();
        if (tool === 'move' || tool === 'line') {
          dragging = selected;
          dragCallout = tool === 'line';
          pin.setPointerCapture(event.pointerId);
          event.preventDefault();
        }
        return;
      }
      if (event.target !== image && !event.target.closest('.qb2-label-lines')) return;
      if (tool !== 'add') return;
      if (markers.length >= 30) { alert('حداکثر ۳۰ نشانه مجاز است.'); return; }
      markers.push({ ...pointerPercent(event, image), lx: null, ly: null, answer: '', synonyms: '', points: 1 });
      selected = markers.length - 1;
      renderLabels(); syncLabels();
      // No scroll: the teacher usually places several markers in a row.
      form.querySelectorAll('[data-label-rows] tr')[selected]?.querySelector('input')?.focus({ preventScroll: true });
    });
    canvas.addEventListener('pointermove', (event) => {
      if (draggingText >= 0) {
        Object.assign(labelTexts[draggingText], pointerPercent(event, image));
        const node = canvas.querySelector(`.qb2-text[data-text-index="${draggingText}"]`);
        node.style.left = `${labelTexts[draggingText].x}%`;
        node.style.top = `${labelTexts[draggingText].y}%`;
        return;
      }
      if (dragging < 0) return;
      const point = pointerPercent(event, image);
      if (dragCallout) Object.assign(markers[dragging], { lx: point.x, ly: point.y });
      else Object.assign(markers[dragging], point);
      placeMarker(dragging);
    });
    canvas.addEventListener('dblclick', (event) => {
      const pin = event.target.closest('.qb2-pin');
      if (!pin || tool !== 'line') return;
      Object.assign(markers[Number(pin.dataset.index)], { lx: null, ly: null });  // back onto the point
      renderLabels(); syncLabels();
    });
    const endDrag = () => {
      if (draggingText >= 0) { draggingText = -1; syncTexts(); }
      if (dragging >= 0) { dragging = -1; syncLabels(); }
    };
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);
    form.querySelectorAll('[data-label-tool]').forEach((button) => button.addEventListener('click', () => {
      tool = button.dataset.labelTool;
      form.querySelectorAll('[data-label-tool]').forEach((other) => {
        other.classList.toggle('is-active', other === button);
        other.setAttribute('aria-pressed', String(other === button));
      });
      canvas.classList.toggle('is-move', tool === 'move');
      canvas.classList.toggle('is-line', tool === 'line');
      canvas.classList.toggle('is-text', tool === 'text');
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
    syncTexts();
  }

  // ----- image hotspot editor: rectangle / circle / polygon regions in % of the stem image -----
  const hotCard = form.querySelector('[data-v2-hotspot]');
  const SHAPE_LABELS = { rect: 'مستطیل', circle: 'دایره', polygon: 'چندضلعی' };
  const SHAPE_ICONS = {
    rect: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="6" width="16" height="12" rx="1.5"/></svg>',
    circle: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/></svg>',
    polygon: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 5 9-1.5 5 7-4 9.5H6.5L3.5 12Z"/></svg>',
  };
  if (hotCard) {
    const regions = (readJson('hotspot-regions', []) || []).filter((item) => item && SHAPE_LABELS[item.shape]).map((item) => ({
      name: item.name || '', shape: item.shape, points: Number(item.points) || 1,
      coords: (item.coords || []).map((point) => [Number(point[0]) || 0, Number(point[1]) || 0]),
    }));
    const canvas = hotCard.querySelector('[data-hot-canvas]');
    const image = canvas.querySelector('[data-hot-image]');
    const svg = canvas.querySelector('[data-hot-svg]');
    const hint = hotCard.querySelector('[data-hot-hint]');
    const SVGNS = 'http://www.w3.org/2000/svg';
    let tool = 'polygon';
    let selectedRegion = -1;
    let draft = null;  // {shape, coords} while drawing
    let drag = null;   // {kind: 'handle'|'move'|'draw', ...}
    let zoom = 100;
    const clamp = (value) => Math.min(Math.max(value, 0), 100);
    const round = (value) => Math.round(value * 100) / 100;
    const syncHot = () => {
      const hidden = form.querySelector('[data-hotspot-json]');
      hidden.value = JSON.stringify(regions.map((item) => ({ ...item, coords: item.coords.map(([x, y]) => [round(x), round(y)]) })));
      changed(hidden);
      const maxClicks = form.querySelector('[data-hot-max-clicks]');
      if (maxClicks && regions.length && num(maxClicks.value, 1) < regions.length) { maxClicks.value = String(regions.length); changed(maxClicks); }
    };
    const toPercent = (event) => {
      const rect = image.getBoundingClientRect();
      return [clamp(((event.clientX - rect.left) / rect.width) * 100), clamp(((event.clientY - rect.top) / rect.height) * 100)];
    };
    const aspect = () => { const rect = image.getBoundingClientRect(); return rect.height ? rect.width / rect.height : 1; };
    const shapeNode = (item, className) => {
      let node;
      if (item.shape === 'rect') {
        const [[x1, y1], [x2, y2]] = item.coords;
        node = document.createElementNS(SVGNS, 'rect');
        node.setAttribute('x', Math.min(x1, x2)); node.setAttribute('y', Math.min(y1, y2));
        node.setAttribute('width', Math.abs(x2 - x1)); node.setAttribute('height', Math.abs(y2 - y1));
      } else if (item.shape === 'circle') {
        const [[cx, cy], [rx, ry]] = item.coords;
        node = document.createElementNS(SVGNS, 'ellipse');
        node.setAttribute('cx', cx); node.setAttribute('cy', cy); node.setAttribute('rx', rx); node.setAttribute('ry', ry);
      } else {
        node = document.createElementNS(SVGNS, item.closed === false ? 'polyline' : 'polygon');
        node.setAttribute('points', item.coords.map(([x, y]) => `${x},${y}`).join(' '));
      }
      node.setAttribute('class', className);
      return node;
    };
    const badgePoint = (item) => {
      if (item.shape === 'rect') return [(item.coords[0][0] + item.coords[1][0]) / 2, Math.min(item.coords[0][1], item.coords[1][1])];
      if (item.shape === 'circle') return [item.coords[0][0], item.coords[0][1] - item.coords[1][1]];
      const xs = item.coords.map((point) => point[0]);
      return [xs.reduce((a, b) => a + b, 0) / xs.length, Math.min(...item.coords.map((point) => point[1]))];
    };
    const handlesOf = (item) => {
      if (item.shape === 'rect') {
        const [[x1, y1], [x2, y2]] = item.coords;
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
      }
      if (item.shape === 'circle') return [item.coords[0], [item.coords[0][0] + item.coords[1][0], item.coords[0][1]]];
      return item.coords;
    };
    const place = (node, [x, y]) => { node.style.left = `${x}%`; node.style.top = `${y}%`; };
    const drawCanvas = () => {
      svg.replaceChildren();
      canvas.querySelectorAll('.qb2-hot-handle, .qb2-hot-badge').forEach((node) => node.remove());
      regions.forEach((item, index) => {
        const node = shapeNode(item, `hs-shape${index === selectedRegion ? ' is-selected' : ''}`);
        node.dataset.index = String(index);
        svg.append(node);
        const badge = el('span', 'qb2-hot-badge', toFa(index + 1));
        place(badge, badgePoint(item));
        canvas.append(badge);
      });
      if (draft) svg.append(shapeNode(draft, 'hs-draft'));
      if (draft?.shape === 'polygon') draft.coords.forEach((point, index) => {
        const handle = el('span', 'qb2-hot-handle');
        handle.style.pointerEvents = index === 0 ? 'auto' : 'none';
        handle.dataset.closePolygon = index === 0 ? '1' : '';
        place(handle, point);
        canvas.append(handle);
      });
      if (selectedRegion >= 0 && regions[selectedRegion] && !draft) {
        handlesOf(regions[selectedRegion]).forEach((point, index) => {
          const handle = el('button', 'qb2-hot-handle');
          handle.type = 'button';
          handle.dataset.handle = String(index);
          handle.setAttribute('aria-label', 'جابجایی گوشه');
          place(handle, point);
          canvas.append(handle);
        });
      }
    };
    const renderHotRows = () => {
      const tbody = hotCard.parentElement.querySelector('[data-hot-rows]') || form.querySelector('[data-hot-rows]');
      tbody.innerHTML = '';
      regions.forEach((item, index) => {
        const tr = el('tr', index === selectedRegion ? 'is-selected' : '');
        tr.addEventListener('focusin', () => { if (selectedRegion !== index) { selectedRegion = index; refreshHot(false); } });
        const numberCell = el('td');
        numberCell.append(el('span', 'qb2-num', toFa(index + 1)));
        const nameCell = el('td');
        const name = el('input');
        name.type = 'text'; name.maxLength = 120; name.value = item.name; name.placeholder = 'دریچه میترال';
        name.dataset.hotName = '';
        name.addEventListener('input', () => { item.name = name.value; syncHot(); });
        nameCell.append(name);
        const shapeCell = el('td');
        const shape = el('span', 'qb2-shape-cell');
        shape.innerHTML = SHAPE_ICONS[item.shape];
        shape.append(SHAPE_LABELS[item.shape]);
        shapeCell.append(shape);
        const pointsCell = el('td');
        const points = el('input');
        points.type = 'number'; points.min = '0'; points.step = '0.5'; points.value = String(item.points);
        points.style.width = '5rem';
        points.addEventListener('input', () => { item.points = Math.max(num(points.value, 0), 0); syncHot(); });
        pointsCell.append(points);
        const actions = el('td');
        const box = el('span', 'qb2-row-actions');
        const edit = el('button', '', 'ویرایش');
        edit.type = 'button';
        edit.addEventListener('click', () => {
          selectedRegion = index;
          refreshHot();
          canvas.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
        const remove = el('button', 'is-danger', 'حذف');
        remove.type = 'button';
        remove.addEventListener('click', () => { regions.splice(index, 1); selectedRegion = -1; refreshHot(); syncHot(); });
        box.append(edit, remove);
        actions.append(box);
        tr.append(numberCell, nameCell, shapeCell, pointsCell, actions);
        tbody.append(tr);
      });
      form.querySelector('[data-hot-empty-rows]').hidden = regions.length > 0;
    };
    const refreshHot = (rows = true) => {
      const src = stemImage();
      if (src && image.src !== src) image.src = src;
      image.hidden = !src;
      svg.style.display = src ? '' : 'none';
      canvas.querySelector('[data-hot-empty]').hidden = !!src;
      const file = hotCard.querySelector('[data-hot-file]');
      file.hidden = !src;
      if (src) {
        const slot = form.querySelector('[data-media-panel="image"] [data-media-slot]');
        const parts = [slot?.querySelector('[data-media-name]')?.textContent.trim(), image.naturalWidth ? `${image.naturalWidth} × ${image.naturalHeight}` : '',
          slot?.querySelector('[data-media-size]')?.textContent.replace('اندازه:', '').trim()].filter(Boolean);
        hotCard.querySelector('[data-hot-file-info]').textContent = parts.join('   ');
      }
      drawCanvas();
      if (rows) renderHotRows();
      else form.querySelectorAll('[data-hot-rows] tr').forEach((tr, index) => tr.classList.toggle('is-selected', index === selectedRegion));
    };
    const finishPolygon = () => {
      if (!draft || draft.shape !== 'polygon') return;
      if (draft.coords.length >= 3) {
        regions.push({ name: '', shape: 'polygon', points: 1, coords: draft.coords });
        selectedRegion = regions.length - 1;
      }
      draft = null;
      refreshHot();
      syncHot();
      form.querySelectorAll('[data-hot-rows] [data-hot-name]')[selectedRegion]?.focus({ preventScroll: true });
    };
    const addRegion = (region) => {
      if (regions.length >= 20) { alert('حداکثر ۲۰ ناحیه مجاز است.'); return; }
      regions.push(region);
      selectedRegion = regions.length - 1;
      refreshHot();
      syncHot();
      form.querySelectorAll('[data-hot-rows] [data-hot-name]')[selectedRegion]?.focus({ preventScroll: true });
    };
    canvas.addEventListener('pointerdown', (event) => {
      if (image.hidden || event.button > 0) return;
      const point = toPercent(event);
      const handle = event.target.closest('[data-handle]');
      if (handle && selectedRegion >= 0) {
        drag = { kind: 'handle', index: Number(handle.dataset.handle) };
        canvas.setPointerCapture(event.pointerId);
        event.preventDefault();
        return;
      }
      if (event.target.closest('[data-close-polygon="1"]') && draft?.coords.length >= 3) { finishPolygon(); return; }
      const shape = event.target.closest('.hs-shape');
      if (shape && !draft) {
        const index = Number(shape.dataset.index);
        selectedRegion = index;
        drag = { kind: 'move', start: point, original: regions[index].coords.map((pair) => [...pair]) };
        canvas.setPointerCapture(event.pointerId);
        refreshHot(false);
        event.preventDefault();
        return;
      }
      if (tool === 'polygon') {
        if (!draft) { draft = { shape: 'polygon', coords: [], closed: false }; selectedRegion = -1; }
        draft.coords.push(point);
        refreshHot(false);
        return;
      }
      selectedRegion = -1;
      draft = tool === 'rect' ? { shape: 'rect', coords: [point, point] } : { shape: 'circle', coords: [point, [0, 0]] };
      drag = { kind: 'draw', start: point, startPx: [event.clientX, event.clientY] };
      canvas.setPointerCapture(event.pointerId);
      event.preventDefault();
      refreshHot(false);
    });
    canvas.addEventListener('pointermove', (event) => {
      if (!drag) return;
      const point = toPercent(event);
      if (drag.kind === 'draw' && draft) {
        if (draft.shape === 'rect') draft.coords[1] = point;
        else {
          const rect = image.getBoundingClientRect();
          const radiusPx = Math.hypot(event.clientX - drag.startPx[0], event.clientY - drag.startPx[1]);
          draft.coords[1] = [radiusPx / rect.width * 100, radiusPx / rect.height * 100];
        }
      } else if (drag.kind === 'move') {
        const item = regions[selectedRegion];
        const dx = point[0] - drag.start[0];
        const dy = point[1] - drag.start[1];
        item.coords = item.shape === 'circle'
          ? [[clamp(drag.original[0][0] + dx), clamp(drag.original[0][1] + dy)], drag.original[1]]
          : drag.original.map(([x, y]) => [clamp(x + dx), clamp(y + dy)]);
      } else if (drag.kind === 'handle') {
        const item = regions[selectedRegion];
        if (item.shape === 'polygon') item.coords[drag.index] = point;
        else if (item.shape === 'circle') {
          if (drag.index === 0) item.coords[0] = point;
          else {
            const dxPercent = Math.abs(point[0] - item.coords[0][0]);
            item.coords[1] = [Math.max(dxPercent, 0.5), Math.max(dxPercent * aspect(), 0.5)];
          }
        } else {
          const [[x1, y1], [x2, y2]] = item.coords;
          const corners = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
          const opposite = corners[(drag.index + 2) % 4];
          item.coords = [opposite, point];
        }
      }
      drawCanvas();
    });
    const endHotDrag = () => {
      if (!drag) return;
      if (drag.kind === 'draw' && draft) {
        const item = draft;
        draft = null;
        const big = item.shape === 'rect'
          ? Math.abs(item.coords[1][0] - item.coords[0][0]) > 1 && Math.abs(item.coords[1][1] - item.coords[0][1]) > 1
          : item.coords[1][0] > 0.8;
        if (big) addRegion({ name: '', shape: item.shape, points: 1, coords: item.coords });
        else refreshHot(false);
      } else {
        const item = regions[selectedRegion];
        if (item?.shape === 'rect') {
          const [[x1, y1], [x2, y2]] = item.coords;
          item.coords = [[Math.min(x1, x2), Math.min(y1, y2)], [Math.max(x1, x2), Math.max(y1, y2)]];
        }
        refreshHot(false);
        syncHot();
      }
      drag = null;
    };
    canvas.addEventListener('pointerup', endHotDrag);
    canvas.addEventListener('pointercancel', endHotDrag);
    canvas.addEventListener('dblclick', (event) => { if (draft?.shape === 'polygon') { event.preventDefault(); draft.coords.pop(); finishPolygon(); } });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && draft) { draft = null; refreshHot(false); }
      if ((event.key === 'Delete') && selectedRegion >= 0 && document.activeElement === document.body) {
        regions.splice(selectedRegion, 1); selectedRegion = -1; refreshHot(); syncHot();
      }
    });
    hotCard.querySelectorAll('[data-hot-tool]').forEach((button) => button.addEventListener('click', () => {
      tool = button.dataset.hotTool;
      if (draft) { draft = null; refreshHot(false); }
      hotCard.querySelectorAll('[data-hot-tool]').forEach((other) => {
        other.classList.toggle('is-active', other === button);
        other.setAttribute('aria-pressed', String(other === button));
      });
    }));
    const setZoom = (value) => {
      zoom = Math.min(Math.max(value, 50), 300);
      canvas.style.width = `${zoom}%`;
      hotCard.querySelector('[data-hot-zoom-value]').textContent = `${zoom}%`;
      drawCanvas();
    };
    hotCard.querySelectorAll('[data-hot-zoom]').forEach((button) => button.addEventListener('click', () => setZoom(zoom + Number(button.dataset.hotZoom) * 25)));
    hotCard.querySelector('[data-hot-reset]').addEventListener('click', () => { draft = null; selectedRegion = -1; setZoom(100); refreshHot(false); });
    form.querySelectorAll('[data-hot-open-image]').forEach((button) => button.addEventListener('click', () => {
      form.querySelector('[data-media-tab="image"]')?.click();
      const panel = form.querySelector('[data-media-panel="image"]');
      panel?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (stemImage()) panel?.querySelector('[data-media-replace]')?.click();
    }));
    form.querySelector('[data-hot-add]')?.addEventListener('click', () => {
      if (!stemImage()) { form.querySelector('[data-hot-open-image]')?.click(); return; }
      canvas.scrollIntoView({ behavior: 'smooth', block: 'center' });
      hint.classList.add('is-flash');
      hint.textContent = `شکل «${SHAPE_LABELS[tool]}» انتخاب است؛ ناحیه را روی تصویر رسم کنید. برای تغییر شکل، از دکمه‌های بالای تصویر استفاده کنید.`;
    });
    image.addEventListener('load', () => refreshHot(false));
    // Alternative text: the side card edits the stem image's «متن جایگزین» field.
    const altSource = form.querySelector('[name="question_image_alt"]');
    const altMirror = form.querySelector('[data-hot-alt]');
    if (altSource && altMirror) {
      const count = form.querySelector('[data-hot-alt-count]');
      const showCount = () => { if (count) count.textContent = `${altMirror.value.length} / 200`; };
      altMirror.value = altSource.value;
      altMirror.addEventListener('input', () => { altSource.value = altMirror.value; changed(altSource); showCount(); });
      altSource.addEventListener('input', () => { altMirror.value = altSource.value; showCount(); });
      showCount();
    }
    const imagePanel = form.querySelector('[data-media-panel="image"]');
    if (imagePanel) new MutationObserver(() => refreshHot(false)).observe(imagePanel, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'src'] });
    refreshHot();
    syncHot();
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
      const lines = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      lines.setAttribute('class', 'qx-label-lines');
      lines.setAttribute('viewBox', '0 0 100 100');
      lines.setAttribute('preserveAspectRatio', 'none');
      stage.append(lines);
      labelTexts.filter((item) => item.text.trim()).forEach((item) => {
        const caption = el('span', 'qx-label-text', item.text);
        caption.style.left = `${item.x}%`;
        caption.style.top = `${item.y}%`;
        stage.append(caption);
      });
      markers.forEach((item, index) => {
        const callout = item.lx != null && item.ly != null;
        const pin = el('span', 'qx-label-pin', toFa(index + 1));
        pin.style.left = `${callout ? item.lx : item.x}%`;
        pin.style.top = `${callout ? item.ly : item.y}%`;
        if (callout) {
          const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
          line.setAttribute('x1', item.lx); line.setAttribute('y1', item.ly); line.setAttribute('x2', item.x); line.setAttribute('y2', item.y);
          lines.append(line);
          const dot = el('span', 'qx-label-anchor');
          dot.style.left = `${item.x}%`;
          dot.style.top = `${item.y}%`;
          stage.append(dot);
        }
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
    hotspot(area) {
      const src = stemImage();
      if (!src) { area.append(el('p', 'qx-select-hint', 'تصویر سؤال هنوز بارگذاری نشده است.')); return; }
      const max = Math.max(1, num(form.querySelector('[data-hot-max-clicks]')?.value, 1));
      const root = el('div', 'qx-hotspot');
      root.dataset.hotspot = '';
      root.dataset.max = String(max);
      const stage = el('div', 'qx-hot-stage');
      const image = el('img');
      image.src = src;
      image.alt = form.querySelector('[name="question_image_alt"]')?.value.trim() || '';
      image.draggable = false;
      stage.append(image);
      const bar = el('div', 'qx-hot-bar');
      const left = el('span', 'qx-hot-left');
      left.dataset.hotspotLeft = '';
      const clear = el('button', 'qx-hot-clear', 'پاک کردن انتخاب‌ها');
      clear.type = 'button';
      clear.dataset.hotspotClear = '';
      bar.append(left, clear);
      const answer = el('input');
      answer.type = 'hidden';
      answer.dataset.hotspotAnswer = '';
      root.append(stage, bar, answer);
      area.append(root);
      window.ExamInteractions.hotspot(root);
    },
    media_response(area) {
      answerHeading(area);
      const formats = [...form.querySelectorAll('[name="answer_formats"]:checked')].map((input) => input.value);
      if (formats.includes('text')) {
        const textarea = el('textarea', 'qx-textarea');
        textarea.placeholder = 'پاسخ خود را بنویسید...';
        area.append(window.QuestionPreview?.richAnswer ? window.QuestionPreview.richAnswer() : textarea);
      }
      const actions = el('div', 'qx-upload-actions');
      const seconds = num(form.querySelector('[name="media_max_record_seconds"]')?.value, 120);
      ['audio', 'video'].forEach((kind) => {
        // The exam page's recorder; in the preview the recording only plays back in this browser.
        if (formats.includes(kind) && window.QuestionPreview) actions.append(window.QuestionPreview.recorder(kind, seconds));
      });
      if (actions.children.length) {
        const box = el('div', 'qx-uploads');
        box.append(actions, el('small', 'qx-upload-hint', 'در پیش‌نمایش ضبط فقط در همین مرورگر پخش می‌شود و ذخیره نمی‌شود.'));
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
