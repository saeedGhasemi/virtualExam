/*
 * Waveform audio player.
 *
 * Wraps every <audio> inside .qb (question builder), .qx (exam page / exam-style preview) or [data-waveform]
 * with a play button, a waveform drawn from the decoded audio and a time readout. The native <audio>
 * stays in the DOM (hidden) and does the actual playback, so form code that reads or revokes its src
 * keeps working. Audio added later (previews, picked files) is picked up by a MutationObserver.
 * If the file cannot be decoded (too large, unsupported codec, network error) the bars are drawn flat
 * and the player still works as a plain seek bar. Opt out with data-no-waveform on the <audio>.
 */
(() => {
  const SCOPE = '.qb, .qx, [data-waveform]';
  const BARS = 64;
  const MAX_DECODE_BYTES = 25 * 1024 * 1024;
  const players = new WeakMap();
  const toFa = (value) => String(value).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const clock = (seconds) => {
    const s = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
    return toFa(`${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`);
  };
  let audioContext = null;

  const style = document.createElement('style');
  style.textContent = `
    .wf-player{display:inline-flex;align-items:center;gap:.6rem;width:min(100%,24rem);min-height:3rem;padding:.35rem .8rem .35rem .4rem;border:1px solid #e4e0fb;border-radius:999px;background:#fff;box-shadow:0 4px 14px rgba(76,29,149,.07);direction:ltr;vertical-align:middle;box-sizing:border-box}
    .wf-player > audio{display:none}
    .wf-play{display:grid;place-items:center;flex:0 0 auto;width:2.3rem;height:2.3rem;padding:0;border:0;border-radius:999px;background:#5b21b6;color:#fff;cursor:pointer}
    .wf-play:hover{background:#4c1d95}
    .wf-play:focus-visible,.wf-wave:focus-visible{outline:2px solid #a78bfa;outline-offset:2px}
    .wf-play svg{width:1rem;height:1rem;fill:currentColor}
    .wf-wave{flex:1 1 auto;min-width:5rem;height:2rem;cursor:pointer;touch-action:none}
    .wf-time{flex:0 0 auto;color:#475569;font:800 .72rem/1 Vazirmatn,Tahoma,sans-serif;white-space:nowrap}
  `;
  document.head.append(style);

  const PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>';
  const PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>';

  const decodePeaks = async (src) => {
    const response = await fetch(src);
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength > MAX_DECODE_BYTES) return null;
    audioContext = audioContext || new (window.AudioContext || window.webkitAudioContext)();
    const decoded = await audioContext.decodeAudioData(buffer);
    const data = decoded.getChannelData(0);
    const step = Math.max(1, Math.floor(data.length / BARS));
    const peaks = [];
    for (let bar = 0; bar < BARS; bar += 1) {
      let peak = 0;
      for (let i = bar * step; i < Math.min((bar + 1) * step, data.length); i += 1) peak = Math.max(peak, Math.abs(data[i]));
      peaks.push(peak);
    }
    const top = Math.max(...peaks) || 1;
    return peaks.map((peak) => Math.max(0.08, peak / top));
  };

  const draw = (player) => {
    const { canvas, audio, peaks } = player;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const progress = audio.duration ? audio.currentTime / audio.duration : 0;
    const gap = 2;
    const barWidth = Math.max(1, (width - gap * (BARS - 1)) / BARS);
    for (let bar = 0; bar < BARS; bar += 1) {
      const level = peaks ? peaks[bar] : 0.18;
      const barHeight = Math.max(2, level * height);
      const x = bar * (barWidth + gap);
      ctx.fillStyle = (bar + 0.5) / BARS <= progress ? '#6d28d9' : '#d8ccfb';
      ctx.fillRect(x, (height - barHeight) / 2, barWidth, barHeight);
    }
    canvas.setAttribute('aria-valuenow', String(Math.round(audio.currentTime || 0)));
    canvas.setAttribute('aria-valuetext', `${clock(audio.currentTime)} از ${clock(audio.duration)}`);
  };

  const updateTime = (player) => {
    player.time.textContent = `${clock(player.audio.currentTime)} / ${clock(player.audio.duration)}`;
    player.canvas.setAttribute('aria-valuemax', String(Math.round(player.audio.duration || 0)));
    draw(player);
  };

  const loadPeaks = (player) => {
    const src = player.audio.currentSrc || player.audio.getAttribute('src');
    if (!src || player.peaksFor === src) return;
    player.peaksFor = src;
    player.peaks = null;
    decodePeaks(src)
      .then((peaks) => { if (player.peaksFor === src) { player.peaks = peaks; draw(player); } })
      .catch(() => { /* undecodable: keep flat bars, playback is unaffected */ });
  };

  const seekTo = (player, clientX) => {
    const { audio, canvas } = player;
    if (!audio.duration) return;
    const rect = canvas.getBoundingClientRect();
    audio.currentTime = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1) * audio.duration;
    updateTime(player);
  };

  const enhance = (audio) => {
    if (players.has(audio) || audio.hasAttribute('data-no-waveform') || !audio.closest(SCOPE)) return;
    // A copy made from another player's innerHTML: drop the inert wrapper and rebuild around the <audio>.
    const stale = audio.parentElement?.classList.contains('wf-player') ? audio.parentElement : null;
    if (stale) stale.replaceWith(audio);

    const wrapper = document.createElement('span');
    wrapper.className = 'wf-player';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'wf-play';
    button.innerHTML = PLAY;
    button.setAttribute('aria-label', 'پخش');
    const canvas = document.createElement('canvas');
    canvas.className = 'wf-wave';
    canvas.tabIndex = 0;
    canvas.setAttribute('role', 'slider');
    canvas.setAttribute('aria-label', 'موقعیت پخش');
    canvas.setAttribute('aria-valuemin', '0');
    const time = document.createElement('span');
    time.className = 'wf-time';
    audio.before(wrapper);
    wrapper.append(button, canvas, time, audio);
    audio.controls = false;
    if (audio.preload === 'none') audio.preload = 'metadata';

    const player = { audio, canvas, time, button, peaks: null, peaksFor: '' };
    players.set(audio, player);
    button.addEventListener('click', () => {
      if (audio.paused) {
        document.querySelectorAll('.wf-player > audio').forEach((other) => { if (other !== audio) other.pause(); });
        audio.play().catch(() => {});
      } else audio.pause();
    });
    audio.addEventListener('play', () => { button.innerHTML = PAUSE; button.setAttribute('aria-label', 'توقف'); });
    audio.addEventListener('pause', () => { button.innerHTML = PLAY; button.setAttribute('aria-label', 'پخش'); });
    ['timeupdate', 'loadedmetadata', 'durationchange', 'ended', 'seeked'].forEach((name) => audio.addEventListener(name, () => updateTime(player)));
    audio.addEventListener('loadedmetadata', () => loadPeaks(player));
    canvas.addEventListener('pointerdown', (event) => {
      canvas.setPointerCapture(event.pointerId);
      seekTo(player, event.clientX);
      const move = (moveEvent) => seekTo(player, moveEvent.clientX);
      canvas.addEventListener('pointermove', move);
      canvas.addEventListener('pointerup', () => canvas.removeEventListener('pointermove', move), { once: true });
    });
    canvas.addEventListener('keydown', (event) => {
      const delta = { ArrowLeft: -5, ArrowRight: 5, ArrowDown: -5, ArrowUp: 5 }[event.key];
      if (!delta || !audio.duration) return;
      event.preventDefault();
      audio.currentTime = Math.min(Math.max(audio.currentTime + delta, 0), audio.duration);
    });
    if ('ResizeObserver' in window) new ResizeObserver(() => draw(player)).observe(canvas);
    updateTime(player);
    if (audio.readyState >= 1) loadPeaks(player);
  };

  const scan = (root) => {
    if (root.tagName === 'AUDIO') enhance(root);
    else root.querySelectorAll?.('audio').forEach(enhance);
  };
  const start = () => {
    scan(document.body);
    new MutationObserver((mutations) => mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
      if (node.nodeType === 1) scan(node);
    }))).observe(document.body, { childList: true, subtree: true });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
