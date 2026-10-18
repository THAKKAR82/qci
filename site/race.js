// Search race: one marked item among N = 1,000,000, both machines at one step per millisecond.
// Classical search checks items in order: about N/2 = 500,000 checks, so about 8 min 20 s.
// Grover's algorithm needs about π/4 × √N ≈ 785 steps, so 0.785 s. After step k the
// probability of measuring the marked item is sin²((2k + 1)θ), with θ = asin(1/√N).
// This illustrates the math, not real hardware.

const section = document.querySelector(".race");

if (section) {
  const N = 1_000_000;
  const THETA = Math.asin(1 / Math.sqrt(N));
  const STEPS = Math.floor(Math.PI / (4 * THETA)); // 785
  const START_LEVEL = 0.35; // every dot equally, faintly lit
  const SKIP_AFTER_MS = 6000;
  const COLORS = {
    paper: [245, 245, 242], // --paper
    line: [220, 221, 216], // --line: idle dots
    ink: [15, 17, 21], // --ink: lit dots
    tint: [235, 235, 230], // --tint: checked dots
  };
  const LEVELS = 48;
  const CHECKED = -1; // brightness value that selects the --tint row

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const mobile = window.matchMedia("(max-width: 767px)");
  const side = (name) => {
    const panel = section.querySelector(`[data-side="${name}"]`);
    const canvas = panel.querySelector("canvas");
    return {
      panel,
      canvas,
      context: canvas.getContext("2d"),
      label: panel.querySelector(".race-label"),
      timer: panel.querySelector("[data-timer]"),
      found: panel.querySelector("[data-found]"),
    };
  };
  const classical = side("classical");
  const run1 = side("quantum");
  const buttons = Object.fromEntries([...section.querySelectorAll("[data-race]")].map((button) => [button.dataset.race, button]));
  const status = section.querySelector("[data-race-status]");
  const caption = section.querySelector("[data-dot-caption]");
  const table = document.querySelector(".race-table");

  let grid = 100;
  let itemsPerDot = N / (grid * grid);
  let marked = 500_000;
  let visible = false;
  let autoStarted = false;
  let frame = 0;
  let lastTime = 0;

  // phase: idle → racing (or static under reduced motion)
  const state = { phase: "idle", classicalMs: 0, classicalDone: false, run1Ms: 0 };

  const format = (ms) => {
    const total = Math.max(0, Math.floor(ms));
    const minutes = String(Math.floor(total / 60000)).padStart(2, "0");
    const seconds = String(Math.floor((total % 60000) / 1000)).padStart(2, "0");
    return `${minutes}:${seconds}.${String(total % 1000).padStart(3, "0")}`;
  };
  const mix = (from, to, t) => from.map((value, i) => Math.round(value + (to[i] - value) * t));
  const pack = ([r, g, b]) => ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
  const markedDot = () => Math.floor(marked / itemsPerDot);

  // Pixel buffer + one anti-aliased dot stamp + a colour table (brightness level × stamp pixel).
  function sizeCanvas(target) {
    const { canvas, context } = target;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = canvas.getBoundingClientRect().width || 1;
    const px = Math.max(1, Math.round(width * ratio));
    canvas.width = px;
    canvas.height = px;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);

    const pitch = width / grid;
    const radius = grid === 100 ? 1.25 : 1.6;
    const r = radius * ratio;
    const reach = Math.ceil(r + 1);
    const offsets = [];
    const alphas = [];
    for (let dy = -reach; dy <= reach; dy += 1) {
      for (let dx = -reach; dx <= reach; dx += 1) {
        const alpha = Math.min(1, Math.max(0, r + 0.5 - Math.hypot(dx, dy)));
        if (alpha > 0) {
          offsets.push(dy * px + dx);
          alphas.push(alpha);
        }
      }
    }
    const rows = LEVELS + 2; // last row is the checked (--tint) colour
    const table = new Uint32Array(rows * alphas.length);
    for (let level = 0; level < rows; level += 1) {
      const color = level <= LEVELS ? mix(COLORS.line, COLORS.ink, level / LEVELS) : COLORS.tint;
      alphas.forEach((alpha, s) => { table[level * alphas.length + s] = pack(mix(COLORS.paper, color, alpha)); });
    }
    const centers = new Int32Array(grid * grid);
    for (let i = 0; i < centers.length; i += 1) {
      const x = Math.round((i % grid + 0.5) * pitch * ratio - 0.5);
      const y = Math.round((Math.floor(i / grid) + 0.5) * pitch * ratio - 0.5);
      centers[i] = Math.min(px * px - 1, Math.max(0, y * px + x));
    }
    const image = context.createImageData(px, px);
    target.render = { pitch, radius, offsets: Int32Array.from(offsets), stamps: alphas.length, table, centers, image, pixels: new Uint32Array(image.data.buffer), size: px };
  }

  function drawDots(target, brightness, overlay) {
    const { pitch, radius, offsets, stamps, table, centers, image, pixels, size } = target.render;
    if (size < 8) return;
    pixels.fill(pack(COLORS.paper));
    for (let i = 0; i < centers.length; i += 1) {
      const value = brightness[i];
      const level = value === CHECKED ? LEVELS + 1 : Math.max(0, Math.min(LEVELS, Math.round(value * LEVELS)));
      const row = level * stamps;
      const center = centers[i];
      for (let s = 0; s < stamps; s += 1) pixels[center + offsets[s]] = table[row + s];
    }
    target.context.putImageData(image, 0, 0);
    if (overlay) overlay(target.context, pitch, radius);
  }

  const dotCenter = (index, pitch) => ({ x: (index % grid + 0.5) * pitch, y: (Math.floor(index / grid) + 0.5) * pitch });
  const ink = (alpha) => `rgba(${COLORS.ink.join(",")}, ${alpha})`;

  // Solid ink dot with a soft ink halo (ink at 15%).
  function solidDot(context, center, radius, strength, halo, maxRadius = radius * 1.8) {
    if (halo > 0) {
      const gradient = context.createRadialGradient(center.x, center.y, 0, center.x, center.y, halo);
      gradient.addColorStop(0, ink(0.15 * strength));
      gradient.addColorStop(1, ink(0));
      context.fillStyle = gradient;
      context.beginPath();
      context.arc(center.x, center.y, halo, 0, Math.PI * 2);
      context.fill();
    }
    context.fillStyle = `rgb(${mix(COLORS.line, COLORS.ink, Math.min(1, strength)).join(",")})`;
    context.beginPath();
    context.arc(center.x, center.y, radius + (maxRadius - radius) * Math.min(1, strength), 0, Math.PI * 2);
    context.fill();
  }

  function ring(context, center, radius, { dashed = false, alpha = 1, width = 1.5 } = {}) {
    context.save();
    context.strokeStyle = ink(alpha);
    context.lineWidth = width;
    if (dashed) context.setLineDash([3, 3]);
    context.beginPath();
    context.arc(center.x, center.y, radius, 0, Math.PI * 2);
    context.stroke();
    context.restore();
  }

  // Classical: dots before the cursor are checked (--tint); the cursor dot is lit.
  let classicalDrawn = "";
  function renderClassical(force = false) {
    const dots = grid * grid;
    const checkedDots = Math.min(dots, Math.floor(state.classicalMs / itemsPerDot));
    classical.timer.textContent = format(state.classicalMs);
    const key = `${checkedDots}|${state.classicalDone}`;
    if (!force && key === classicalDrawn) return;
    classicalDrawn = key;
    const brightness = new Float32Array(dots).fill(START_LEVEL);
    brightness.fill(CHECKED, 0, checkedDots);
    if (!state.classicalDone && state.phase === "racing" && checkedDots < dots) brightness[checkedDots] = 1;
    drawDots(classical, brightness, (context, pitch, radius) => {
      if (!state.classicalDone) return;
      const center = dotCenter(markedDot(), pitch);
      solidDot(context, center, radius, 1, 0);
      ring(context, center, pitch * 1.6);
    });
  }

  // The quantum run: light drains from every dot and flows into the answer.
  function renderQuantum(ms) {
    const progress = Math.min(1, ms / STEPS);
    const k = Math.round(STEPS * progress);
    const p = Math.sin((2 * k + 1) * THETA) ** 2;
    const dots = grid * grid;
    const target = markedDot();
    const brightness = new Float32Array(dots);
    const others = START_LEVEL * (1 - p);
    const tx = target % grid;
    const ty = Math.floor(target / grid);
    // A faint ripple leaves the marked dot every 50 steps so the motion reads even at 785 ms.
    const rippleRadius = progress > 0 && progress < 1 ? ((k % 50) / 50) * grid * 0.9 : -10;
    for (let i = 0; i < dots; i += 1) {
      let value = others;
      const distance = Math.hypot((i % grid) - tx, Math.floor(i / grid) - ty);
      if (Math.abs(distance - rippleRadius) < 1.5) value += 0.12 * (1 - p * 0.6);
      brightness[i] = value;
    }
    brightness[target] = 0;
    const level = START_LEVEL + (1 - START_LEVEL) * p;
    drawDots(run1, brightness, (context, pitch, radius) => {
      // The answer marker grows to a clearly visible size (at least 5px) as the light settles.
      solidDot(context, dotCenter(target, pitch), radius, level, pitch * 6 * p, Math.max(5, pitch * 1.5));
    });
    run1.timer.textContent = format(k);
  }

  function renderAll(force = false) {
    renderClassical(force);
    renderQuantum(state.run1Ms);
  }

  function tick(time) {
    frame = 0;
    const delta = Math.min(100, time - (lastTime || time));
    lastTime = time;
    if (!visible) return;

    if (state.phase === "racing") {
      if (!state.classicalDone) {
        state.classicalMs += delta;
        if (state.classicalMs >= marked + 1) finishClassical(false);
        else {
          if (state.classicalMs >= SKIP_AFTER_MS) buttons.skip.hidden = false;
          renderClassical();
        }
      }
    }
    if (state.phase === "racing" && state.run1Ms < STEPS) {
      state.run1Ms = Math.min(STEPS, state.run1Ms + delta);
      renderQuantum(state.run1Ms);
      if (state.run1Ms >= STEPS) finishQuantum();
    }
    // Keep ticking while the normal computer is still checking.
    if (state.phase === "racing" && (!state.classicalDone || state.run1Ms < STEPS)) frame = requestAnimationFrame(tick);
  }

  function loop() {
    if (!frame && visible) {
      lastTime = 0;
      frame = requestAnimationFrame(tick);
    }
  }

  function finishQuantum() {
    run1.timer.classList.add("is-found");
    run1.found.hidden = false;
    buttons.replay.hidden = false;
    status.textContent = `Quantum computer found the dot in ${STEPS} steps, ${format(STEPS)}. The normal computer is still checking.`;
  }

  function finishClassical(skipped) {
    state.classicalDone = true;
    state.classicalMs = marked + 1;
    buttons.skip.hidden = true;
    classical.found.hidden = false;
    renderClassical(true);
    status.textContent = `${skipped ? "Skipped ahead. " : ""}Normal computer found the dot after ${format(state.classicalMs)}.`;
  }

  function pickTarget() {
    // Middle two rows of the 100×100 grid, away from the edges: the item index stays within
    // about 1.5% of N/2, so the normal computer still lands near the 08:20 average.
    const row = 49 + Math.round(Math.random());
    const column = 25 + Math.floor(Math.random() * 50);
    marked = (row * 100 + column) * 100 + Math.floor(Math.random() * 100);
  }

  function reset() {
    cancelAnimationFrame(frame);
    frame = 0;
    buttons.skip.hidden = true;
    buttons.replay.hidden = true;
    Object.assign(state, { phase: "idle", classicalMs: 0, classicalDone: false, run1Ms: 0 });
    for (const target of [classical, run1]) {
      target.found.hidden = true;
      target.timer.classList.remove("is-found");
    }
    layout();
  }

  function startRace() {
    autoStarted = true;
    reset();
    pickTarget();
    buttons.start.hidden = true;
    state.phase = "racing";
    status.textContent = "Race started. Both machines take one step per millisecond.";
    loop();
  }

  function layout() {
    grid = mobile.matches ? 60 : 100;
    itemsPerDot = N / (grid * grid);
    caption.textContent = mobile.matches ? "Each dot is about 280 items." : "Each dot is 100 items.";
    for (const target of [classical, run1]) sizeCanvas(target);
    renderAll(true);
  }

  // Reduced motion: no race. Show both final states statically.
  function renderStatic() {
    pickTarget();
    Object.assign(state, { phase: "static", classicalMs: marked + 1, classicalDone: true, run1Ms: STEPS });
    classical.found.hidden = false;
    run1.timer.classList.add("is-found");
    run1.found.hidden = false;
    buttons.start.hidden = true;
    buttons.replay.hidden = true;
    layout();
  }

  buttons.start.addEventListener("click", startRace);
  buttons.replay.addEventListener("click", startRace);
  buttons.skip.addEventListener("click", () => finishClassical(true));

  const resizer = new ResizeObserver(() => {
    for (const target of [classical, run1]) sizeCanvas(target);
    renderAll(true);
  });
  for (const target of [classical, run1]) resizer.observe(target.canvas);
  mobile.addEventListener("change", layout);

  // Pause every clock while the section is off-screen; resume when it returns.
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    if (visible) loop();
  }).observe(section);

  // Auto-start once when the panels are half visible.
  if (!reducedMotion.matches) {
    new IntersectionObserver(([entry]) => {
      if (entry.intersectionRatio < 0.5 || autoStarted) return;
      visible = true;
      startRace();
    }, { threshold: 0.5 }).observe(section.querySelector(".race-panels"));
  }

  // Scale table rows fade in one by one.
  if (table && !reducedMotion.matches) {
    table.classList.add("will-reveal");
    new IntersectionObserver(([entry], observer) => {
      if (!entry.isIntersecting) return;
      table.classList.add("is-revealed");
      observer.disconnect();
    }, { threshold: 0.3 }).observe(table);
  }

  if (reducedMotion.matches) renderStatic();
  else layout();
}
