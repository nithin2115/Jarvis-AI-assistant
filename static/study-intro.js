/**
 * Study Mode cinematic intro — particles, typewriter quote, loader, TTS sync.
 */

const STUDY_QUOTES = [
  'Practice Here — Makes You Job Ready.',
  'Every Expert Was Once a Beginner.',
  'Discipline Creates Success.',
  'Train Your Mind Like Iron.',
  'Your Future Is Built One Session At A Time.',
  'Consistency Beats Talent.',
  'Learning Never Stops.',
];

const LOADER_LINES = [
  'INITIALIZING STUDY MODE...',
  'LOADING AI LEARNING SYSTEM...',
  'PREPARING SIMULATION MODULES...',
  'READY.',
];

const TIMING = {
  enter: 600,
  typeStart: 800,
  charMs: 34,
  loaderStart: 2300,
  loaderLineMs: 320,
  complete: 4400,
};

let _lastQuoteIdx = -1;
let _abort = null;
let _rafId = 0;
let _speaking = false;
let _ambience = null;

function pickQuote() {
  let idx;
  do {
    idx = Math.floor(Math.random() * STUDY_QUOTES.length);
  } while (idx === _lastQuoteIdx && STUDY_QUOTES.length > 1);
  _lastQuoteIdx = idx;
  return STUDY_QUOTES[idx];
}

function formatSpeakText(display) {
  let s = display.replace(/\s*—\s*/g, '… ').trim();
  if (s.endsWith('.')) s = s.slice(0, -1);
  s = s.toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1) + '.';
}

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function particleCount() {
  const cores = navigator.hardwareConcurrency || 4;
  const mem = navigator.deviceMemory || 4;
  if (cores >= 8 && mem >= 8) return 70;
  if (cores >= 4) return 55;
  return 40;
}

function delay(ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    if (_abort) _abort.timers = _abort.timers || [];
    _abort.timers.push(t);
    _abort.reject = reject;
  });
}

function createAbort() {
  return { aborted: false, timers: [], reject: null };
}

function abortIntro(ctrl) {
  if (!ctrl) return;
  ctrl.aborted = true;
  (ctrl.timers || []).forEach(clearTimeout);
  if (ctrl.reject) try { ctrl.reject(new DOMException('Aborted', 'AbortError')); } catch (_) {}
  cancelAnimationFrame(_rafId);
  _rafId = 0;
  stopAmbience();
  const q = document.getElementById('study-cine-quote');
  if (q) q.classList.remove('speaking', 'visible');
}

function startParticles(canvas, ctrl) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d', { alpha: true });
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let W = 0;
  let H = 0;
  const n = particleCount();
  const pts = [];
  for (let i = 0; i < n; i++) {
    pts.push({
      x: Math.random(),
      y: Math.random(),
      vx: (Math.random() - 0.5) * 0.0008,
      vy: (Math.random() - 0.5) * 0.0008,
      r: 0.8 + Math.random() * 1.8,
      hue: Math.random() < 0.5 ? 270 : 300,
    });
  }

  function resize() {
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();
  window.addEventListener('resize', resize);

  let t0 = performance.now();
  function tick(now) {
    if (ctrl.aborted) return;
    _rafId = requestAnimationFrame(tick);
    const t = (now - t0) / 1000;
    const boost = _speaking ? 1.8 : 1;
    ctx.clearRect(0, 0, W, H);
    for (const p of pts) {
      p.x += p.vx * boost;
      p.y += p.vy * boost;
      if (p.x < 0 || p.x > 1) p.vx *= -1;
      if (p.y < 0 || p.y > 1) p.vy *= -1;
      const px = p.x * W;
      const py = p.y * H;
      const pulse = _speaking ? 0.5 + 0.5 * Math.sin(t * 3 + p.x * 10) : 0.35;
      ctx.beginPath();
      ctx.arc(px, py, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `hsla(${p.hue}, 70%, 65%, ${pulse * 0.5})`;
      ctx.fill();
    }
  }
  _rafId = requestAnimationFrame(tick);
  ctrl.cleanupParticles = () => {
    cancelAnimationFrame(_rafId);
    _rafId = 0;
    window.removeEventListener('resize', resize);
  };
}

function startAmbience() {
  if (localStorage.getItem('study_ambience') !== '1') return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 82;
    lfo.frequency.value = 0.08;
    lfoGain.gain.value = 8;
    lfo.connect(lfoGain);
    lfoGain.connect(osc.frequency);
    gain.gain.value = 0.04;
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    lfo.start();
    _ambience = { ctx, gain, base: 0.04 };
  } catch (_) {}
}

function duckAmbience() {
  if (_ambience?.gain) _ambience.gain.gain.value = 0.012;
}

function restoreAmbience() {
  if (_ambience?.gain) _ambience.gain.gain.value = _ambience.base || 0.04;
}

function stopAmbience() {
  if (!_ambience) return;
  try {
    _ambience.ctx.close();
  } catch (_) {}
  _ambience = null;
}

async function typewriter(el, text, ctrl) {
  el.textContent = '';
  el.classList.add('visible');
  const cursor = document.createElement('span');
  cursor.className = 'study-cursor';
  for (let i = 0; i < text.length; i++) {
    if (ctrl.aborted) return;
    el.textContent = text.slice(0, i + 1);
    el.appendChild(cursor);
    await delay(TIMING.charMs);
  }
  if (!ctrl.aborted) cursor.remove();
}

async function runLoader(ctrl) {
  const loader = document.getElementById('study-cine-loader');
  const lineEl = loader?.querySelector('.study-cine-load-line');
  if (!loader || !lineEl) return;
  loader.classList.add('visible');
  for (const line of LOADER_LINES) {
    if (ctrl.aborted) return;
    lineEl.textContent = line;
    await delay(TIMING.loaderLineMs);
  }
}

async function requestStudyTts(text) {
  try {
    const res = await fetch('/api/tts/study', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    return res.ok;
  } catch (e) {
    console.warn('[STUDY] TTS request failed', e);
    return false;
  }
}

export function setStudySpeaking(on) {
  _speaking = !!on;
  const q = document.getElementById('study-cine-quote');
  if (q) q.classList.toggle('speaking', _speaking);
  if (_speaking) duckAmbience();
  else restoreAmbience();
}

export function abortStudyIntro() {
  abortIntro(_abort);
  _abort = null;
}

export async function startStudyIntro({ onComplete } = {}) {
  const cinematic = document.getElementById('study-cinematic');
  const quoteEl = document.getElementById('study-cine-quote');
  const canvas = document.getElementById('study-cine-particles');
  const loader = document.getElementById('study-cine-loader');
  if (!cinematic || !quoteEl) {
    onComplete?.();
    return;
  }

  abortStudyIntro();
  const ctrl = createAbort();
  _abort = ctrl;

  const reduced = prefersReducedMotion();
  const quote = pickQuote();
  const speakText = formatSpeakText(quote);

  cinematic.classList.remove('fade-out');
  cinematic.classList.add('active');
  cinematic.setAttribute('aria-hidden', 'false');
  quoteEl.classList.remove('visible', 'speaking');
  if (loader) {
    loader.classList.remove('visible');
    const le = loader.querySelector('.study-cine-load-line');
    if (le) le.textContent = '';
  }

  if (!reduced) {
    startParticles(canvas, ctrl);
    startAmbience();
  }

  const tStart = performance.now();

  try {
    if (reduced) {
      quoteEl.textContent = quote;
      quoteEl.classList.add('visible');
      await requestStudyTts(speakText);
      await delay(800);
      onComplete?.();
      return;
    }

    await delay(TIMING.enter);
    if (ctrl.aborted) return;

    await delay(TIMING.typeStart - TIMING.enter);
    if (ctrl.aborted) return;
    requestStudyTts(speakText);
    await typewriter(quoteEl, quote, ctrl);
    if (ctrl.aborted) return;

    let elapsed = performance.now() - tStart;
    await delay(Math.max(0, TIMING.loaderStart - elapsed));
    if (ctrl.aborted) return;
    await runLoader(ctrl);
    if (ctrl.aborted) return;

    elapsed = performance.now() - tStart;
    await delay(Math.max(0, TIMING.complete - elapsed));
    if (ctrl.aborted) return;

    cinematic.classList.add('fade-out');
    await delay(400);
    if (ctrl.aborted) return;
    onComplete?.();
  } catch (e) {
    if (e?.name !== 'AbortError') console.warn('[STUDY] intro error', e);
    if (!ctrl.aborted) onComplete?.();
  } finally {
    ctrl.cleanupParticles?.();
    stopAmbience();
    if (!ctrl.aborted) {
      cinematic.classList.remove('active', 'fade-out');
      cinematic.setAttribute('aria-hidden', 'true');
    }
    _abort = null;
  }
}
