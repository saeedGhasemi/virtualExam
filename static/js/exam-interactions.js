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
 *   ExamInteractions.recorder(box, { kind, maxSeconds, maxBytes, wavRate, onRecorded, onError, onState })
 *     in-browser audio/video recording (student answers and the question builder). Inside box: [data-record-toggle]
 *     buttons start/stop, [data-record-wave] canvas shows the live input level, [data-record-time] the clock
 *     («mm:ss / max»), [data-record-live] holds the camera preview, [data-record-label] the toggle's text.
 *     Audio is converted to 16-bit mono WAV at wavRate Hz (default 16000) so every browser can play and seek it
 *     (Chrome's WebM recordings carry no duration); onRecorded(file) gets the File, onError(message) a problem.
 *     [data-record-status] shows each step and the exact reason when recording cannot start (permission, no device,
 *     device busy, no https). Returns { start, stop, reset, supported, setState }.
 *   ExamInteractions.hotspot(root)
 *     image hotspot answer: root[data-max] = allowed clicks; clicks on .qx-hot-stage img become numbered markers
 *     (a click on a marker removes it) and go to [data-hotspot-answer] as «x,y;x,y» in % of the image.
 *   ExamInteractions.richAnswer(box)
 *     essay answer editor (Quill, when loaded): keeps the posted plain text and Delta fields and a word count in sync.
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
        media.closest('.wf-player')?.classList.add('is-exhausted');  // the waveform player's play button
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


  // ----- in-browser recording -----
  const RECORD_TYPES = {
    audio: ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/ogg'],
    video: ['video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4'],
  };
  const recordType = (kind) => (RECORD_TYPES[kind] || []).find((type) => window.MediaRecorder?.isTypeSupported?.(type)) || '';
  const recordExtension = (type, kind) => {
    if (type.includes('mp4')) return kind === 'video' ? 'mp4' : 'm4a';
    return type.includes('ogg') ? 'ogg' : 'webm';
  };
  const clockText = (seconds) => toFa(`${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`);

  // Decoded recording -> mono 16-bit PCM WAV at `rate` Hz.
  const toWav = async (blob, rate) => {
    const Context = window.AudioContext || window.webkitAudioContext;
    const context = new Context();
    let decoded;
    try { decoded = await context.decodeAudioData(await blob.arrayBuffer()); } finally { context.close?.(); }
    const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const samples = (await offline.startRendering()).getChannelData(0);
    const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
    const text = (offset, value) => [...value].forEach((char, i) => view.setUint8(offset + i, char.charCodeAt(0)));
    text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, 'data'); view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i += 1) view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 0x7fff, true);
    return new Blob([view.buffer], { type: 'audio/wav' });
  };

  // Why recording cannot start, in words the user can act on.
  const recordError = (error, kind) => {
    const name = error?.name || '';
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      return kind === 'video'
        ? 'اجازه‌ی دسترسی به دوربین/میکروفون داده نشد. روی نماد قفل کنار نشانی سایت بزنید، دوربین و میکروفون را «مجاز» کنید و دوباره امتحان کنید.'
        : 'اجازه‌ی دسترسی به میکروفون داده نشد. روی نماد قفل کنار نشانی سایت بزنید، میکروفون را «مجاز» کنید و دوباره امتحان کنید.';
    }
    if (name === 'NotFoundError' || name === 'OverconstrainedError') {
      return kind === 'video' ? 'دوربینی روی این دستگاه پیدا نشد؛ دوربین را وصل کنید یا فایل ویدئو را بارگذاری کنید.' : 'میکروفونی روی این دستگاه پیدا نشد؛ میکروفون را وصل کنید یا فایل صوتی را بارگذاری کنید.';
    }
    if (name === 'NotReadableError' || name === 'AbortError') {
      return 'دوربین یا میکروفون در دسترس نیست؛ احتمالاً برنامه یا زبانه‌ی دیگری (مثلاً تماس تصویری) از آن استفاده می‌کند. آن را ببندید و دوباره امتحان کنید.';
    }
    return `ضبط شروع نشد (${name || 'خطای ناشناخته'})؛ صفحه را دوباره بارگذاری کنید یا فایل را بارگذاری کنید.`;
  };
  const recordUnsupported = () => (window.isSecureContext === false
    ? 'ضبط در مرورگر فقط روی اتصال امن (https) ممکن است؛ سایت را با https باز کنید یا فایل را بارگذاری کنید.'
    : 'این مرورگر ضبط صدا/ویدئو را پشتیبانی نمی‌کند؛ از نسخه‌ی تازه‌ی Chrome، Edge، Firefox یا Safari استفاده کنید یا فایل را بارگذاری کنید.');

  // States reported through onState(state, text) and shown in [data-record-status]:
  // idle, asking, recording, processing, error (the page adds its own: uploading, saved).
  const recorder = (box, { kind = 'audio', maxSeconds = 0, maxBytes = 0, wavRate = 16000, onRecorded = () => {}, onError = () => {}, onState = () => {} } = {}) => {
    const supported = !!(window.MediaRecorder && navigator.mediaDevices?.getUserMedia);
    const toggles = [...box.querySelectorAll('[data-record-toggle]')];
    const wave = box.querySelector('[data-record-wave]');
    const time = box.querySelector('[data-record-time]');
    const live = box.querySelector('[data-record-live]');
    const status = box.querySelector('[data-record-status]');
    const labels = [...box.querySelectorAll('[data-record-label]')];
    const idleLabels = labels.map((label) => label.textContent);
    let media = null;
    let stream = null;
    let audioContext = null;
    let analyser = null;
    let levels = [];
    let frame = 0;
    let ticker = 0;
    let seconds = 0;
    let busy = false;

    const setState = (state, text = '') => {
      box.dataset.recordState = state;
      if (status) {
        status.textContent = text;
        status.hidden = !text;
        status.classList.toggle('is-error', state === 'error');
      }
      onState(state, text);
    };
    const fail = (message) => { setState('error', message); onError(message); };
    const drawWave = () => {
      if (!wave) return;
      const width = wave.clientWidth;
      const height = wave.clientHeight;
      if (!width || !height) return;
      const ratio = window.devicePixelRatio || 1;
      if (wave.width !== Math.round(width * ratio)) { wave.width = Math.round(width * ratio); wave.height = Math.round(height * ratio); }
      const ctx = wave.getContext('2d');
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, height);
      const bars = Math.max(12, Math.floor(width / 5));
      for (let bar = 0; bar < bars; bar += 1) {
        const level = levels[levels.length - bars + bar] ?? 0;
        const barHeight = Math.max(2, Math.min(1, level) * height);
        ctx.fillStyle = level ? '#ef4444' : '#d6dbe6';
        ctx.fillRect(width - (bars - bar) * 5, (height - barHeight) / 2, 3, barHeight);
      }
    };
    const showTime = () => {
      if (time) time.textContent = maxSeconds ? `${clockText(seconds)} / ${clockText(maxSeconds)}` : clockText(seconds);
    };
    const sample = () => {
      if (!analyser) return;
      const data = new Uint8Array(analyser.fftSize);
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      data.forEach((value) => { sum += ((value - 128) / 128) ** 2; });
      levels.push(Math.min(1, Math.sqrt(sum / data.length) * 4));
      if (levels.length > 400) levels = levels.slice(-400);
      drawWave();
      frame = window.requestAnimationFrame(sample);
    };
    const setRecording = (on) => {
      box.classList.toggle('is-recording', on);
      toggles.forEach((button) => button.setAttribute('aria-pressed', on ? 'true' : 'false'));
      labels.forEach((label, index) => { label.textContent = on ? 'پایان ضبط' : idleLabels[index]; });
    };
    const release = () => {
      window.cancelAnimationFrame(frame);
      clearInterval(ticker);
      if (stream) stream.getTracks().forEach((track) => track.stop());
      if (audioContext) audioContext.close?.();
      stream = null; audioContext = null; analyser = null;
      if (live) { live.replaceChildren(); live.hidden = true; }
    };
    const finish = async (chunks, type) => {
      const extension = recordExtension(type, kind);
      let blob = new Blob(chunks, { type: type || `${kind}/${extension}` });
      if (!blob.size) { fail('چیزی ضبط نشد؛ دوباره امتحان کنید.'); return; }
      setState('processing', 'در حال آماده‌سازی فایل ضبط‌شده...');
      let name = `recording-${Date.now()}`;
      if (kind === 'audio' && wavRate) {
        try { blob = await toWav(blob, wavRate); name += '.wav'; } catch (error) { name += `.${extension}`; }
      } else {
        name += `.${extension}`;
      }
      if (maxBytes && blob.size > maxBytes) {
        fail(`حجم فایل ضبط‌شده (${toFa((blob.size / 1048576).toFixed(1))} مگابایت) بیش از حد مجاز است؛ کوتاه‌تر ضبط کنید.`);
        return;
      }
      setState('idle', '');
      onRecorded(new File([blob], name, { type: blob.type }));
    };
    let startedAt = 0;
    const stop = () => {
      if (!media || media.state !== 'recording') return;
      const early = 1000 - (performance.now() - startedAt);
      if (early > 0) { setTimeout(stop, early); return; }  // at least one second, never an empty take
      try { media.requestData(); } catch (error) { /* not supported: stop() still flushes */ }
      media.stop();
    };
    const start = async () => {
      if (media || busy) return;
      if (!supported) { fail(recordUnsupported()); return; }
      busy = true;
      // Created inside the click (a user gesture) so the browser lets it run: the live level needs it.
      try {
        const Context = window.AudioContext || window.webkitAudioContext;
        audioContext = new Context();
        audioContext.resume?.();
      } catch (error) { audioContext = null; }
      setState('asking', kind === 'video' ? 'در حال درخواست دسترسی به دوربین و میکروفون؛ در پنجره‌ی مرورگر «اجازه» را بزنید.' : 'در حال درخواست دسترسی به میکروفون؛ در پنجره‌ی مرورگر «اجازه» را بزنید.');
      let silentVideo = false;
      try {
        stream = await navigator.mediaDevices.getUserMedia(kind === 'video' ? { audio: true, video: true } : { audio: true });
      } catch (error) {
        // A camera without a microphone (common on desktops) still records a silent video.
        if (kind === 'video' && ['NotFoundError', 'OverconstrainedError', 'NotReadableError'].includes(error?.name)) {
          try { stream = await navigator.mediaDevices.getUserMedia({ video: true }); silentVideo = true; } catch (second) { stream = null; }
        }
        if (!stream) {
          busy = false;
          if (audioContext) audioContext.close?.();
          audioContext = null;
          fail(recordError(error, kind));
          return;
        }
      }
      if (kind === 'video') {
        // Cameras need a moment before the first frame; recording before that gives an empty file.
        setState('asking', 'در حال آماده‌سازی دوربین...');
        const preview = document.createElement('video');
        preview.muted = true; preview.autoplay = true; preview.playsInline = true;
        preview.srcObject = stream;
        if (live) { live.replaceChildren(preview); live.hidden = false; }
        await new Promise((resolve) => {
          const ready = () => resolve();
          preview.addEventListener('loadeddata', ready, { once: true });
          preview.play?.().catch(() => {});
          setTimeout(ready, 3000);
        });
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      if (audioContext && stream.getAudioTracks().length) {
        try {
          analyser = audioContext.createAnalyser();
          analyser.fftSize = 512;
          audioContext.createMediaStreamSource(stream).connect(analyser);
        } catch (error) { analyser = null; }
      }
      const type = recordType(kind);
      const options = type ? { mimeType: type } : {};
      if (kind === 'video') options.videoBitsPerSecond = 1000000;
      const chunks = [];
      try { media = new MediaRecorder(stream, options); } catch (error) {
        try { media = new MediaRecorder(stream); } catch (second) { busy = false; release(); fail(recordError(second, kind)); return; }
      }
      const current = media;
      let lateData = null;
      current.addEventListener('dataavailable', (event) => {
        if (event.data.size) chunks.push(event.data);
        if (lateData && chunks.length) lateData();
      });
      current.addEventListener('error', (event) => fail(recordError(event.error, kind)));
      current.addEventListener('stop', async () => {
        const usedType = current.mimeType || type;
        setRecording(false);
        // Some browsers deliver the last piece just after «stop» (seen with short takes): wait for it briefly
        // before giving up, and only then release the camera/microphone.
        if (!chunks.length) await new Promise((resolve) => { lateData = resolve; setTimeout(resolve, 1500); });
        media = null;
        busy = false;
        release();
        finish(chunks, usedType);
      });
      levels = [];
      seconds = 0;
      showTime();
      current.start(250);
      startedAt = performance.now();
      setRecording(true);
      setState('recording', silentVideo ? 'در حال ضبط ویدئو (بدون صدا: میکروفونی پیدا نشد)...' : 'در حال ضبط...');
      if (analyser) frame = window.requestAnimationFrame(sample);
      ticker = setInterval(() => {
        seconds += 1;
        showTime();
        if (maxSeconds && seconds >= maxSeconds) stop();
      }, 1000);
    };
    const reset = () => {
      stop();
      levels = [];
      seconds = 0;
      showTime();
      drawWave();
      setState('idle', '');
    };
    toggles.forEach((button) => button.addEventListener('click', () => (media ? stop() : start())));
    if (!supported) {
      // Not hidden: the user sees why recording is unavailable here (and can still upload a file).
      box.classList.add('is-unsupported');
      setState('error', recordUnsupported());
    }
    showTime();
    if ('ResizeObserver' in window && wave) new ResizeObserver(drawWave).observe(wave);
    drawWave();
    return { start, stop, reset, supported, setState };
  };


  // ----- image hotspot: the student clicks the image; each click is a numbered marker, a click on one removes it -----
  const hotspot = (root) => {
    const stage = root.querySelector('.qx-hot-stage');
    const image = stage?.querySelector('img');
    const answer = root.querySelector('[data-hotspot-answer]');
    const left = root.querySelector('[data-hotspot-left]');
    const max = Math.max(1, Number(root.dataset.max || 1));
    if (!stage || !image || !answer) return;
    const clicks = (answer.value || '').split(';').map((part) => part.split(',').map(Number))
      .filter((pair) => pair.length === 2 && pair.every((value) => Number.isFinite(value))).slice(0, max);
    const render = () => {
      stage.querySelectorAll('.qx-hot-mark').forEach((mark) => mark.remove());
      clicks.forEach(([x, y], index) => {
        const mark = document.createElement('button');
        mark.type = 'button';
        mark.className = 'qx-hot-mark';
        mark.style.left = `${x}%`;
        mark.style.top = `${y}%`;
        mark.textContent = toFa(index + 1);
        mark.setAttribute('aria-label', `برداشتن انتخاب ${toFa(index + 1)}`);
        mark.addEventListener('click', (event) => {
          event.stopPropagation();
          if (root.closest('fieldset:disabled')) return;
          clicks.splice(index, 1);
          sync();
        });
        stage.append(mark);
      });
      if (left) left.textContent = `${toFa(clicks.length)} از ${toFa(max)} انتخاب${clicks.length >= max ? ' — برای تغییر، روی یکی از نقطه‌ها کلیک کنید تا برداشته شود' : ''}`;
      root.classList.toggle('is-full', clicks.length >= max);
    };
    const sync = () => {
      answer.value = clicks.map(([x, y]) => `${Math.round(x * 100) / 100},${Math.round(y * 100) / 100}`).join(';');
      notify(answer);
      render();
    };
    image.addEventListener('click', (event) => {
      if (root.closest('fieldset:disabled')) return;
      if (clicks.length >= max) {
        if (max !== 1) { root.classList.add('is-shake'); setTimeout(() => root.classList.remove('is-shake'), 400); return; }
        clicks.length = 0;  // a single allowed click simply moves
      }
      const rect = image.getBoundingClientRect();
      clicks.push([Math.min(Math.max((event.clientX - rect.left) / rect.width * 100, 0), 100), Math.min(Math.max((event.clientY - rect.top) / rect.height * 100, 0), 100)]);
      sync();
    });
    root.querySelector('[data-hotspot-clear]')?.addEventListener('click', () => {
      if (root.closest('fieldset:disabled')) return;
      clicks.length = 0;
      sync();
    });
    render();
  };


  // ----- essay answer editor (Quill): bold, italic, lists, link, undo/redo, word count -----
  // box: [data-rich-editor], [data-rich-toolbar], the posted plain-text textarea [data-rich-text] (shown when Quill
  // is missing), the posted Delta [data-rich-delta], an optional initial Delta <script> and [data-word-count].
  const richAnswer = (box) => {
    const text = box.querySelector('[data-rich-text]');
    const deltaInput = box.querySelector('[data-rich-delta]');
    const editor = box.querySelector('[data-rich-editor]');
    const counter = box.querySelector('[data-word-count]');
    const words = (value) => value.split(/\s+/).filter(Boolean).length;
    const showCount = (value) => { if (counter) counter.textContent = `${toFa(words(value))} کلمه`; };
    if (!window.Quill || !text || !editor) {
      box.classList.add('is-plain');
      text?.addEventListener('input', () => showCount(text.value));
      showCount(text?.value || '');
      return null;
    }
    const quill = new window.Quill(editor, {
      theme: 'snow',
      placeholder: text.getAttribute('placeholder') || 'پاسخ خود را اینجا بنویسید...',
      modules: {
        history: { delay: 800, maxStack: 200, userOnly: true },
        toolbar: {
          container: box.querySelector('[data-rich-toolbar]'),
          handlers: { undo() { this.quill.history.undo(); }, redo() { this.quill.history.redo(); } },
        },
      },
    });
    let initial = null;
    try { initial = JSON.parse(box.querySelector('script[type="application/json"]')?.textContent || 'null'); } catch (error) { initial = null; }
    if (initial && Array.isArray(initial.ops)) quill.setContents(initial, 'silent');
    else if (text.value.trim()) quill.setText(text.value, 'silent');
    quill.root.setAttribute('dir', 'auto');
    box.classList.add('is-rich');
    const sync = (announce) => {
      const plain = quill.getText().trim();
      text.value = plain;
      deltaInput.value = plain ? JSON.stringify(quill.getContents()) : '';
      showCount(plain);
      if (announce) notify(text);
    };
    quill.on('text-change', () => sync(true));
    sync(false);
    if (box.closest('fieldset:disabled')) quill.disable();
    return quill;
  };

  window.ExamInteractions = { ordering, matching, limitChoices, voiceInput, matrix, imageLabel, playback, recorder, hotspot, richAnswer };
})();
