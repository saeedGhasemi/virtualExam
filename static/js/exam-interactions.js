/*
 * Answer interactions shared by the student exam screen and the question builder's exam-style preview,
 * so both behave identically. Elements are found by data attributes; styling stays with each page.
 *
 *   ExamInteractions.ordering(list, answerInput)
 *     list: container whose children carry data-value (draggable); optional [data-ordering-badge] inside each.
 *     answerInput: receives the order as "v1,v2,..." and fires `input` (the exam autosave listens for it).
 *   ExamInteractions.matching(root, answerInput)
 *     root: holds [data-side="left"|"right"][data-value] nodes and an <svg data-matching-lines>;
 *     root[data-many-to-one] allows several left items to share one right item.
 *     answerInput: receives "left:right,..." and fires `input`.
 *   ExamInteractions.limitChoices(root, max)
 *     multi-answer: once `max` checkboxes inside root are checked, the others are disabled (0 = no limit).
 *   ExamInteractions.voiceInput(button, target)
 *     speech-to-text into a text input (fa-IR); the button stays hidden where the browser lacks SpeechRecognition.
 *   ExamInteractions.matrix(root, answerInput)
 *     matrix question: the checked [data-matrix-cell] inputs (value "row:column") go to answerInput as "r1:c2,...".
 *   ExamInteractions.imageLabel(root)
 *     image labelling; root[data-label-drag] = drag mode: [data-label-chip] buttons are dragged (or clicked, then a
 *     field clicked) into the read-only [data-label-input] fields; [data-label-clear] empties a field.
 *   ExamInteractions.playback(media, { maxPlays, start, end, storageKey })
 *     audio/video stimulus rules in the browser: play count (0 = unlimited) and the allowed [start, end] seconds.
 *     The count survives reloads via localStorage when storageKey is given. This is a client-side limit only.
 */
(() => {
  const toFa = (value) => String(value).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const notify = (input) => input.dispatchEvent(new Event('input', { bubbles: true }));

  const ordering = (list, answerInput) => {
    const items = () => Array.from(list.children).filter((item) => item.dataset.value !== undefined);
    const renumber = () => {
      items().forEach((item, index) => {
        const badge = item.querySelector('[data-ordering-badge]');
        if (badge) badge.textContent = toFa(index + 1);
      });
      answerInput.value = items().map((item) => item.dataset.value).join(',');
      notify(answerInput);
    };
    (answerInput.value || '').split(',').filter(Boolean).forEach((value) => {
      const item = items().find((candidate) => candidate.dataset.value === value);
      if (item) list.appendChild(item);
    });
    let dragged = null;
    items().forEach((item) => {
      item.draggable = true;
      item.addEventListener('dragstart', () => { dragged = item; item.classList.add('is-dragging'); });
      item.addEventListener('dragend', () => { dragged = null; item.classList.remove('is-dragging'); renumber(); });
    });
    list.addEventListener('dragover', (event) => {
      event.preventDefault();
      if (!dragged) return;
      const after = items().filter((item) => item !== dragged).find((item) => event.clientY < item.getBoundingClientRect().top + item.getBoundingClientRect().height / 2);
      list.insertBefore(dragged, after || null);
    });
    renumber();
  };

  const matching = (root, answerInput) => {
    const linesSvg = root.querySelector('[data-matching-lines]');
    const leftNodes = Array.from(root.querySelectorAll('[data-side="left"]'));
    const rightNodes = Array.from(root.querySelectorAll('[data-side="right"]'));
    const manyToOne = root.hasAttribute('data-many-to-one');
    const pairs = {};
    let selectedLeft = null;

    const nodeCenter = (node) => {
      const box = node.getBoundingClientRect();
      const rootBox = root.getBoundingClientRect();
      return { x: box.left + box.width / 2 - rootBox.left, y: box.top + box.height / 2 - rootBox.top };
    };
    const redraw = () => {
      if (!linesSvg) return;
      linesSvg.innerHTML = '';
      Object.entries(pairs).forEach(([leftValue, rightValue]) => {
        const leftNode = leftNodes.find((n) => n.dataset.value === leftValue);
        const rightNode = rightNodes.find((n) => n.dataset.value === rightValue);
        if (!leftNode || !rightNode) return;
        const a = nodeCenter(leftNode);
        const b = nodeCenter(rightNode);
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', `M${a.x} ${a.y} C ${(a.x + b.x) / 2} ${a.y}, ${(a.x + b.x) / 2} ${b.y}, ${b.x} ${b.y}`);
        linesSvg.appendChild(path);
      });
    };
    const refreshPaired = () => {
      leftNodes.forEach((n) => n.classList.toggle('is-paired', n.dataset.value in pairs));
      rightNodes.forEach((n) => n.classList.toggle('is-paired', Object.values(pairs).includes(n.dataset.value)));
    };
    const setPair = (leftValue, rightValue) => {
      if (!manyToOne) Object.keys(pairs).forEach((key) => { if (pairs[key] === rightValue) delete pairs[key]; });
      pairs[leftValue] = rightValue;
      refreshPaired();
      redraw();
      answerInput.value = Object.entries(pairs)
        .sort((a, b) => Number(a[0]) - Number(b[0]))
        .map(([leftValue, rightValue]) => `${leftValue}:${rightValue}`)
        .join(',');
      notify(answerInput);
    };
    leftNodes.forEach((node) => node.addEventListener('click', () => {
      leftNodes.forEach((n) => n.classList.remove('is-selected'));
      selectedLeft = node.dataset.value;
      node.classList.add('is-selected');
    }));
    rightNodes.forEach((node) => node.addEventListener('click', () => {
      if (!selectedLeft) return;
      setPair(selectedLeft, node.dataset.value);
      leftNodes.forEach((n) => n.classList.remove('is-selected'));
      selectedLeft = null;
    }));
    (answerInput.value || '').split(',').filter(Boolean).forEach((pair) => {
      const [leftValue, rightValue] = pair.split(':');
      if (leftValue && rightValue) pairs[leftValue] = rightValue;
    });
    refreshPaired();
    window.requestAnimationFrame(redraw);
    window.addEventListener('resize', redraw);
    return { redraw };
  };

  const limitChoices = (root, max) => {
    if (!max) return;
    const boxes = Array.from(root.querySelectorAll('input[type="checkbox"]'));
    const enforce = () => {
      const full = boxes.filter((box) => box.checked).length >= max;
      boxes.forEach((box) => { box.disabled = full && !box.checked; });
    };
    root.addEventListener('change', enforce);
    enforce();
  };

  const voiceInput = (button, target) => {
    const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!button || !target || !SpeechRecognitionImpl) return;
    button.hidden = false;
    const recognizer = new SpeechRecognitionImpl();
    recognizer.lang = 'fa-IR';
    recognizer.interimResults = false;
    recognizer.maxAlternatives = 1;
    let isRecording = false;
    const stopped = () => { isRecording = false; button.classList.remove('is-recording'); };
    recognizer.addEventListener('result', (event) => {
      const transcript = Array.from(event.results).map((result) => result[0].transcript).join(' ').trim();
      if (!transcript) return;
      target.value = target.value ? `${target.value} ${transcript}` : transcript;
      notify(target);
    });
    recognizer.addEventListener('end', stopped);
    recognizer.addEventListener('error', stopped);
    button.addEventListener('click', () => {
      if (isRecording) { recognizer.stop(); return; }
      isRecording = true;
      button.classList.add('is-recording');
      recognizer.start();
    });
  };

  const matrix = (root, answerInput) => {
    const sync = () => {
      answerInput.value = Array.from(root.querySelectorAll('[data-matrix-cell]:checked')).map((input) => input.value).join(',');
      notify(answerInput);
    };
    root.addEventListener('change', (event) => { if (event.target.matches('[data-matrix-cell]')) sync(); });
  };

  const imageLabel = (root) => {
    if (!root.hasAttribute('data-label-drag')) return;
    const fields = Array.from(root.querySelectorAll('[data-label-input]'));
    let picked = null;
    const markUsed = () => {
      const used = fields.map((field) => field.value);
      root.querySelectorAll('[data-label-chip]').forEach((chip) => chip.classList.toggle('is-used', used.includes(chip.textContent.trim())));
    };
    const place = (field, text) => {
      field.value = text;
      notify(field);
      markUsed();
    };
    root.addEventListener('dragstart', (event) => {
      const chip = event.target.closest('[data-label-chip]');
      if (chip) event.dataTransfer.setData('text/plain', chip.textContent.trim());
    });
    fields.forEach((field) => {
      field.addEventListener('dragover', (event) => event.preventDefault());
      field.addEventListener('drop', (event) => {
        event.preventDefault();
        place(field, event.dataTransfer.getData('text/plain'));
      });
      // Touch and keyboard: pick a chip, then the field.
      field.addEventListener('click', () => {
        if (!picked) return;
        place(field, picked.textContent.trim());
        picked.classList.remove('is-picked');
        picked = null;
      });
    });
    root.addEventListener('click', (event) => {
      const chip = event.target.closest('[data-label-chip]');
      if (chip) {
        picked?.classList.remove('is-picked');
        picked = picked === chip ? null : chip;
        picked?.classList.add('is-picked');
        return;
      }
      const clear = event.target.closest('[data-label-clear]');
      if (clear) place(clear.parentElement.querySelector('[data-label-input]'), '');
    });
    markUsed();
  };

  const playback = (media, { maxPlays = 0, start = null, end = null, storageKey = '' } = {}) => {
    if (!media) return;
    const from = Number(start) || 0;
    const until = end === null || end === undefined || end === '' ? null : Number(end);
    const read = () => { try { return Number(localStorage.getItem(storageKey) || 0); } catch (error) { return 0; } };
    const write = (value) => { try { if (storageKey) localStorage.setItem(storageKey, String(value)); } catch (error) { /* storage unavailable */ } };
    let plays = storageKey ? read() : 0;
    let fresh = true;
    const note = document.createElement('small');
    note.className = 'qx-playback-note';
    media.after(note);
    const refresh = () => {
      const left = maxPlays ? Math.max(maxPlays - plays, 0) : null;
      const range = from || until !== null ? ` — بازه‌ی پخش: ${toFa(clock(from))} تا ${until !== null ? toFa(clock(until)) : 'پایان'}` : '';
      note.textContent = maxPlays ? `دفعات پخش باقی‌مانده: ${toFa(left)} از ${toFa(maxPlays)}${range}` : range.replace(/^ — /, '');
      if (maxPlays && left <= 0 && fresh) {
        media.pause();
        media.controls = false;
        media.classList.add('is-exhausted');
      }
    };
    const clock = (seconds) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
    const finish = () => {
      media.pause();
      fresh = true;
      media.currentTime = from;
      refresh();
    };
    media.addEventListener('loadedmetadata', () => { if (media.currentTime < from) media.currentTime = from; });
    media.addEventListener('play', () => {
      if (!fresh) return;
      if (maxPlays && plays >= maxPlays) { media.pause(); refresh(); return; }
      fresh = false;
      plays += 1;
      write(plays);
      if (media.currentTime < from || (until !== null && media.currentTime >= until)) media.currentTime = from;
      refresh();
    });
    media.addEventListener('timeupdate', () => { if (until !== null && media.currentTime >= until) finish(); });
    media.addEventListener('seeking', () => {
      if (media.currentTime < from) media.currentTime = from;
      else if (until !== null && media.currentTime > until) media.currentTime = until;
    });
    media.addEventListener('ended', finish);
    refresh();
  };

  window.ExamInteractions = { ordering, matching, limitChoices, voiceInput, matrix, imageLabel, playback };
})();
