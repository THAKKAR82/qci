// Quotes section: rotating quotes with a pixel portrait drawn as particles.
// Portraits come only from the pre-made bit maps in ./portraits (no photos are loaded or processed).

const section = document.querySelector(".quotes");

if (section) {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const mobile = window.matchMedia("(max-width: 767px)");

  const PORTRAITS = {
    lloyd: {
      label: "Pixel portrait of Seth Lloyd",
      name: "Seth Lloyd",
      body: "Professor at MIT who proposed one of the first practical designs for a quantum computer.",
      credit: null, // TODO: add the source photo's credit and license before launch.
    },
    jensen: {
      label: "Pixel portrait of Jensen Huang",
      name: "Jensen Huang",
      body: "Co-founder and CEO of NVIDIA, whose chips power most of today's AI.",
      credit: null, // TODO: add the source photo's credit and license before launch.
    },
    pichai: {
      label: "Pixel portrait of Sundar Pichai",
      name: "Sundar Pichai",
      body: "CEO of Google and Alphabet. Google built Willow, one of the most advanced quantum chips.",
      credit: null, // TODO: add the source photo's credit and license before launch.
    },
    chip: {
      label: "Pixel illustration of qubits on a chip",
      ask: "What's this?", // a chip, not a person
      name: "Google Quantum AI",
      body: "Google's quantum computing lab. This pixel grid is an illustration of qubits on a chip, not a real chip layout.",
      credit: null, // An illustration, so no photo credit.
    },
    feynman: {
      label: "Pixel portrait of Richard Feynman",
      name: "Richard Feynman",
      body: "Nobel Prize-winning physicist (1918–1988) who first proposed building computers out of quantum physics.",
      credit: null, // TODO: add the source photo's credit and license before launch.
    },
  };

  const INK = [15, 17, 21];
  const Q = [39, 76, 159]; // --q, the Bloch sphere's blue
  const PAPER = [245, 245, 242];
  const MORPH_MS = 900;
  const RIPPLE_MS = 300;
  const ROTATE_MS = 8000;

  // ---------- Rotating quotes ----------
  const slides = [...section.querySelectorAll(".quote-slide")];
  const dots = [...section.querySelectorAll(".quote-dot")];
  const pauseButton = section.querySelector(".quote-pause");
  const carousel = section.querySelector(".quotes-carousel");
  const live = section.querySelector(".quote-slides");
  const credit = section.querySelector("[data-credit]");
  const whoName = section.querySelector("[data-who-name]");
  const whoBody = section.querySelector("[data-who-body]");
  const whoLabel = section.querySelector("[data-who-label]");
  let current = 0;
  let timer = 0;
  let userPaused = reducedMotion.matches;
  let hovering = false;
  let focused = false;
  let onScreen = false;

  function describe(key) {
    const info = PORTRAITS[key];
    canvas.setAttribute("aria-label", info.label);
    whoLabel.textContent = info.ask ?? "Who is this?";
    whoName.textContent = info.name;
    whoBody.textContent = info.body;
    credit.textContent = info.credit ?? "";
    credit.hidden = !info.credit;
  }

  function show(index, { announce = false } = {}) {
    const previousKey = slides[current].dataset.portrait;
    current = (index + slides.length) % slides.length;
    slides.forEach((slide, i) => { slide.hidden = i !== current; });
    dots.forEach((dot, i) => dot.setAttribute("aria-current", String(i === current)));
    live.setAttribute("aria-live", announce ? "polite" : "off");
    const key = slides[current].dataset.portrait;
    describe(key);
    // A new face morphs; the same face (Pichai twice) gets a quick ripple instead.
    if (key !== previousKey) morphTo(key);
    else ripple(res / 2, res / 2);
  }

  function schedule() {
    clearTimeout(timer);
    timer = 0;
    if (userPaused || hovering || focused || !onScreen) return;
    timer = setTimeout(() => {
      show(current + 1);
      schedule();
    }, ROTATE_MS);
  }

  function setPaused(paused) {
    userPaused = paused;
    pauseButton.textContent = paused ? "Play" : "Pause";
    pauseButton.setAttribute("aria-pressed", String(paused));
    schedule();
  }

  dots.forEach((dot, i) => dot.addEventListener("click", () => {
    if (i !== current) show(i, { announce: true });
    schedule();
  }));
  pauseButton.addEventListener("click", () => setPaused(!userPaused));
  carousel.addEventListener("pointerenter", () => { hovering = true; schedule(); });
  carousel.addEventListener("pointerleave", () => { hovering = false; schedule(); });
  carousel.addEventListener("focusin", () => { focused = true; schedule(); });
  carousel.addEventListener("focusout", (event) => {
    if (carousel.contains(event.relatedTarget)) return;
    focused = false;
    schedule();
  });

  // Swipe left or right on the quotes to change them.
  let swipeStart = null;
  carousel.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "mouse") swipeStart = { x: event.clientX, y: event.clientY };
  });
  carousel.addEventListener("pointerup", (event) => {
    if (!swipeStart) return;
    const dx = event.clientX - swipeStart.x;
    const dy = event.clientY - swipeStart.y;
    swipeStart = null;
    if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.5) {
      show(current + (dx < 0 ? 1 : -1), { announce: true });
      schedule();
    }
  });

  // ---------- Particle portrait ----------
  const canvas = section.querySelector(".portrait-canvas");
  const context = canvas.getContext("2d");
  const bits = {};
  let res = mobile.matches ? 48 : 96;
  let particles = [];
  let ready = false;
  let revealed = false;
  let frame = 0;
  let lastTime = 0;
  let pointer = null; // { x, y } in cells while the pointer is over the canvas
  let morph = null; // { start }
  let rippleWave = null; // { x, y, start }

  const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
  const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

  function cellsOf(key, size) {
    const rows = bits[key]?.[String(size)];
    const cells = [];
    if (!rows) return cells;
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; x += 1) if (row[x] === "1") cells.push({ x, y });
    });
    return cells;
  }

  // Every cell is a whole number of device pixels: the backing size is a multiple of 96 (and so of
  // 48, 24 and 12), and the CSS size is set to match, so squares stay crisp and identical.
  function sizeCanvas() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const available = canvas.parentElement.getBoundingClientRect().width || 1;
    const cellPx = Math.max(1, Math.floor((available * ratio) / 96));
    const backing = cellPx * 96;
    canvas.width = backing;
    canvas.height = backing;
    canvas.style.width = `${backing / ratio}px`;
  }

  // Draw a plain bit map (used for the 12 → 24 → 48 → 96 resolve and for reduced motion).
  function drawBits(key, size) {
    const { width } = canvas;
    const cell = width / size;
    context.fillStyle = `rgb(${PAPER})`;
    context.fillRect(0, 0, width, width);
    context.fillStyle = `rgb(${INK})`;
    for (const { x, y } of cellsOf(key, size)) {
      context.fillRect(Math.floor(x * cell), Math.floor(y * cell), Math.ceil(cell), Math.ceil(cell));
    }
  }

  function makeParticles(key) {
    particles = cellsOf(key, res).map(({ x, y }) => ({ hx: x, hy: y, x, y, vx: 0, vy: 0, alpha: 1, tint: 0 }));
  }

  function draw() {
    const { width } = canvas;
    const cell = width / res;
    context.fillStyle = `rgb(${PAPER})`;
    context.fillRect(0, 0, width, width);
    // Group by quantized tint and alpha so fillStyle changes stay few.
    const buckets = new Map();
    for (const p of particles) {
      if (p.alpha <= 0.02) continue;
      const key = `${Math.round(p.tint * 8)}|${Math.round(p.alpha * 8)}`;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(p);
    }
    for (const [key, list] of buckets) {
      const [tint, alpha] = key.split("|").map((v) => Number(v) / 8);
      context.fillStyle = `rgba(${mix(INK, Q, tint)}, ${alpha})`;
      for (const p of list) context.fillRect(Math.round(p.x * cell), Math.round(p.y * cell), cell, cell);
    }
  }

  // Pair particles with target cells by angle around the centre, then distance, so the move swirls.
  function morphTo(key) {
    if (!ready) return;
    // Reduced motion: an instant swap between static 96×96 portraits.
    if (reducedMotion.matches) return drawBits(key, 96);
    // Before the first resolve finishes, the resolve itself picks up the current portrait.
    if (!revealed) return;
    const centre = res / 2;
    const order = (a, b) => a.angle - b.angle || a.dist - b.dist;
    const polar = (x, y) => ({ angle: Math.atan2(y - centre, x - centre), dist: Math.hypot(x - centre, y - centre) });
    const from = particles.filter((p) => p.alpha > 0.5).map((p) => ({ p, ...polar(p.hx, p.hy) })).sort(order);
    const to = cellsOf(key, res).map((c) => ({ c, ...polar(c.x, c.y) })).sort(order);
    const next = [];
    const now = performance.now();
    const fly = (p, c) => {
      p.from = { x: p.x, y: p.y };
      p.hx = c.x;
      p.hy = c.y;
      p.delay = Math.random() * 150;
      p.fade = 0;
      next.push(p);
    };
    if (from.length >= to.length) {
      const used = new Set();
      to.forEach((t, j) => {
        const i = Math.floor((j * from.length) / to.length);
        used.add(i);
        fly(from[i].p, t.c);
      });
      // Extra particles fade out where they are.
      from.forEach((f, i) => {
        if (used.has(i)) return;
        f.p.fade = -1;
        f.p.from = { x: f.p.x, y: f.p.y };
        f.p.hx = f.p.x;
        f.p.hy = f.p.y;
        f.p.delay = 0;
        next.push(f.p);
      });
    } else {
      const used = new Set();
      from.forEach((f, i) => {
        const j = Math.floor((i * to.length) / from.length);
        used.add(j);
        fly(f.p, to[j].c);
      });
      // Missing particles fade in at their target.
      to.forEach((t, j) => {
        if (used.has(j)) return;
        next.push({ hx: t.c.x, hy: t.c.y, x: t.c.x, y: t.c.y, vx: 0, vy: 0, alpha: 0, tint: 0, from: { x: t.c.x, y: t.c.y }, delay: Math.random() * 150, fade: 1 });
      });
    }
    particles = next;
    morph = { start: now };
    start();
  }

  function ripple(cx, cy) {
    if (!ready || reducedMotion.matches || !revealed) return;
    rippleWave = { x: cx, y: cy, start: performance.now() };
    start();
  }

  // Step the morph, the ripple, the pointer push and the springs. Returns true while anything moves.
  function step(now) {
    let moving = false;
    const radius = res * 0.14;
    const maxPush = 3;

    if (morph) {
      const elapsed = now - morph.start;
      for (const p of particles) {
        if (!p.from) continue;
        const t = Math.min(1, Math.max(0, (elapsed - p.delay) / (MORPH_MS - 150)));
        const e = easeInOut(t);
        if (p.fade === -1) p.alpha = 1 - e;
        else if (p.fade === 1) p.alpha = e;
        else {
          p.x = p.from.x + (p.hx - p.from.x) * e;
          p.y = p.from.y + (p.hy - p.from.y) * e;
          p.tint = Math.sin(Math.PI * t); // blue in flight, ink on landing
        }
      }
      if (elapsed >= MORPH_MS) {
        particles = particles.filter((p) => p.fade !== -1);
        for (const p of particles) {
          p.x = p.hx;
          p.y = p.hy;
          p.alpha = 1;
          p.tint = 0;
          delete p.from;
        }
        morph = null;
      }
      moving = true;
    }

    let ringRadius = -1;
    if (rippleWave) {
      const t = (now - rippleWave.start) / RIPPLE_MS;
      if (t >= 1) rippleWave = null;
      else {
        ringRadius = t * res * 0.8;
        moving = true;
      }
    }

    if (!morph) {
      for (const p of particles) {
        let tx = p.hx;
        let ty = p.hy;
        if (pointer) {
          const dx = p.hx - pointer.x;
          const dy = p.hy - pointer.y;
          const d = Math.hypot(dx, dy);
          if (d < radius && d > 0.001) {
            const push = maxPush * (1 - d / radius) ** 2;
            tx += (dx / d) * push;
            ty += (dy / d) * push;
          }
        }
        if (ringRadius > 0) {
          const dx = p.hx - rippleWave.x;
          const dy = p.hy - rippleWave.y;
          const d = Math.hypot(dx, dy) || 1;
          const band = Math.exp(-(((d - ringRadius) / 2.5) ** 2));
          tx += (dx / d) * band * 1.5;
          ty += (dy / d) * band * 1.5;
        }
        // Spring toward the (pushed) target: stiffness 0.08, damping 0.82.
        p.vx = (p.vx + (tx - p.x) * 0.08) * 0.82;
        p.vy = (p.vy + (ty - p.y) * 0.08) * 0.82;
        p.x += p.vx;
        p.y += p.vy;
        const displacement = Math.hypot(p.x - p.hx, p.y - p.hy);
        p.tint = Math.min(1, displacement / maxPush);
        if (displacement > 0.01 || Math.abs(p.vx) + Math.abs(p.vy) > 0.005) moving = true;
        else {
          p.x = p.hx;
          p.y = p.hy;
          p.vx = 0;
          p.vy = 0;
          p.tint = 0;
        }
      }
    }
    return moving || Boolean(pointer);
  }

  function tick(time) {
    frame = 0;
    if (!onScreen) return;
    lastTime = time;
    const keepGoing = step(time);
    draw();
    if (keepGoing) frame = requestAnimationFrame(tick);
  }

  function start() {
    if (!frame && onScreen && !reducedMotion.matches) frame = requestAnimationFrame(tick);
  }

  // Pointer: hovering (or dragging on touch) pushes particles away; a tap sends a ripple.
  function toCells(event) {
    const rect = canvas.getBoundingClientRect();
    return { x: ((event.clientX - rect.left) / rect.width) * res, y: ((event.clientY - rect.top) / rect.height) * res };
  }
  let touchStart = null;
  canvas.addEventListener("pointermove", (event) => {
    if (!revealed || reducedMotion.matches) return;
    pointer = toCells(event);
    if (touchStart && Math.hypot(event.clientX - touchStart.x, event.clientY - touchStart.y) > 8) touchStart.moved = true;
    start();
  });
  canvas.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "mouse") touchStart = { x: event.clientX, y: event.clientY, moved: false };
  });
  canvas.addEventListener("pointerup", (event) => {
    if (touchStart && !touchStart.moved) {
      const { x, y } = toCells(event);
      ripple(x, y);
    }
    touchStart = null;
    if (event.pointerType !== "mouse") pointer = null;
  });
  for (const type of ["pointerleave", "pointercancel"]) {
    canvas.addEventListener(type, () => {
      pointer = null;
      touchStart = null;
      start();
    });
  }

  // First appearance: resolve 12 → 24 → 48 → 96 (180 ms per step), then hand over to particles.
  function resolve() {
    const key = slides[current].dataset.portrait;
    const steps = [12, 24, 48, 96].filter((size) => size <= res);
    steps.forEach((size, i) => setTimeout(() => drawBits(key, size), i * 180));
    setTimeout(() => {
      makeParticles(slides[current].dataset.portrait);
      revealed = true;
      draw();
    }, steps.length * 180);
  }

  function relayout() {
    res = mobile.matches ? 48 : 96;
    sizeCanvas();
    if (!ready) return;
    const key = slides[current].dataset.portrait;
    if (reducedMotion.matches) return drawBits(key, 96);
    if (!revealed) return drawBits(key, 12);
    makeParticles(key);
    draw();
  }

  async function load() {
    const keys = Object.keys(PORTRAITS);
    const data = await Promise.all(keys.map((key) => fetch(`./portraits/${key}-bits.json`).then((r) => r.json())));
    keys.forEach((key, i) => { bits[key] = data[i]; });
    ready = true;
    if (reducedMotion.matches) {
      revealed = true;
      relayout();
      return;
    }
    relayout();
    if (inView) resolve();
  }

  let inView = false;
  new ResizeObserver(relayout).observe(canvas.parentElement);
  mobile.addEventListener("change", relayout);
  new IntersectionObserver(([entry]) => {
    onScreen = entry.isIntersecting;
    schedule();
    if (onScreen) start();
  }).observe(section);
  new IntersectionObserver(([entry], observer) => {
    if (!entry.isIntersecting) return;
    observer.disconnect();
    inView = true;
    if (ready && !revealed) resolve();
  }, { threshold: 0.4 }).observe(canvas);

  describe(slides[current].dataset.portrait);
  dots.forEach((dot, i) => dot.setAttribute("aria-current", String(i === current)));
  setPaused(userPaused);
  load().catch(() => {});
}
