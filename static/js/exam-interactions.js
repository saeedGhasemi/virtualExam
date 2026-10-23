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

  window.ExamInteractions = { ordering, matching, limitChoices, voiceInput };
})();
