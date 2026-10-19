// "Every qubit doubles it.": five stops showing the memory a normal computer needs to store the
// full quantum state of n qubits exactly (2^n values × 16 bytes), in things people can picture.
// Checks: 2^30 × 16 B = 16 GiB, 2^40 × 16 B = 16 TiB, 2^50 × 16 B = 16 PiB (Frontier, the largest
// supercomputer, has about 9 PB of memory), 2^70 × 16 B = 16 ZiB (about all data ever stored),
// 2^105 × 16 B = 2^109 B ≈ 6.5 × 10^32 B ≈ 650,000,000,000 ZB. Willow has 105 qubits.

const section = document.querySelector(".qubits");

if (section) {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const STEP_MS = 1600;
  const FADE_MS = 250;

  const ICONS = {
    laptop: '<path d="M14 18h36a2 2 0 0 1 2 2v22H12V20a2 2 0 0 1 2-2Z"/><path d="M6 42h52l-3 6H9z"/>',
    servers: '<rect x="14" y="8" width="36" height="12" rx="2"/><rect x="14" y="26" width="36" height="12" rx="2"/><rect x="14" y="44" width="36" height="12" rx="2"/><path d="M20 14h4M20 32h4M20 50h4"/><circle cx="43" cy="14" r="1.5"/><circle cx="43" cy="32" r="1.5"/><circle cx="43" cy="50" r="1.5"/>',
    building: '<path d="M12 56V18l20-10 20 10v38"/><path d="M6 56h52"/><path d="M22 26h4M30 26h4M38 26h4M22 34h4M30 34h4M38 34h4M22 42h4M30 42h4M38 42h4"/><path d="M28 56v-6h8v6"/>',
    globe: '<circle cx="32" cy="32" r="22"/><path d="M10 32h44"/><path d="M32 10c7 6 10 14 10 22s-3 16-10 22c-7-6-10-14-10-22s3-16 10-22Z"/><path d="M14 20h36M14 44h36"/>',
    chip: '<rect x="16" y="16" width="32" height="32" rx="3"/><rect x="25" y="25" width="14" height="14" rx="1.5"/><path d="M24 16V8M32 16V8M40 16V8M24 56v-8M32 56v-8M40 56v-8M16 24H8M16 32H8M16 40H8M56 24h-8M56 32h-8M56 40h-8"/>',
  };

  const STOPS = {
    30: { line: "About a laptop.", memory: "16 GB", icon: "laptop" },
    40: { line: "A shelf of servers.", memory: "16 TB", icon: "servers" },
    50: { line: "More than the world's biggest supercomputer.", memory: "16 PB", icon: "building" },
    70: { line: "Roughly all the data humanity has ever stored.", memory: "16 ZB", icon: "globe" },
    105: {
      line: "Billions of times all the data on Earth.",
      memory: "≈ 650,000,000,000 ZB",
      icon: "chip",
      extra: "Google's Willow chip has 105 qubits. It exists today.",
      key: true,
    },
  };
  const ORDER = [30, 40, 50, 70, 105];

  const buttons = [...section.querySelectorAll("[data-q-stop]")];
  const card = section.querySelector("[data-q-card]");
  const icon = section.querySelector("[data-q-icon]");
  const count = section.querySelector("[data-q-count]");
  const line = section.querySelector("[data-q-line]");
  const memory = section.querySelector("[data-q-memory]");
  const extra = section.querySelector("[data-q-extra]");
  let current = null;
  let fadeTimer = 0;
  let autoTimer = 0;

  function fill(n) {
    const stop = STOPS[n];
    icon.innerHTML = `<svg viewBox="0 0 64 64" width="64" height="64" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[stop.icon]}</svg>`;
    count.textContent = `${n} qubits`;
    line.textContent = stop.line;
    memory.textContent = stop.memory;
    extra.textContent = stop.extra ?? "";
    extra.hidden = !stop.extra;
    card.classList.toggle("is-key", Boolean(stop.key));
  }

  function select(n, { focus = false } = {}) {
    if (n === current) return;
    current = n;
    buttons.forEach((b) => {
      const on = Number(b.dataset.qStop) === n;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    clearTimeout(fadeTimer);
    if (reducedMotion.matches) return fill(n);
    card.classList.add("is-out");
    fadeTimer = setTimeout(() => {
      fill(n);
      card.classList.remove("is-out");
    }, FADE_MS);
  }

  function stopAutoPlay() {
    clearTimeout(autoTimer);
    autoTimer = 0;
  }

  buttons.forEach((b) => b.addEventListener("click", () => {
    stopAutoPlay();
    select(Number(b.dataset.qStop));
  }));
  // Arrow keys move between stops (a radio group), Home/End jump to the ends.
  section.querySelector(".qubits-stops").addEventListener("keydown", (event) => {
    const index = ORDER.indexOf(current);
    const next = { ArrowRight: index + 1, ArrowDown: index + 1, ArrowLeft: index - 1, ArrowUp: index - 1, Home: 0, End: ORDER.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    stopAutoPlay();
    select(ORDER[Math.max(0, Math.min(ORDER.length - 1, next))], { focus: true });
  });

  if (reducedMotion.matches) {
    select(105);
  } else {
    select(30);
    // First time the section is half visible: step through every stop once, ending on 105.
    new IntersectionObserver(([entry], observer) => {
      if (entry.intersectionRatio < 0.5) return;
      observer.disconnect();
      let i = 0;
      const next = () => {
        i += 1;
        if (i >= ORDER.length) return;
        select(ORDER[i]);
        autoTimer = setTimeout(next, STEP_MS);
      };
      autoTimer = setTimeout(next, STEP_MS);
    }, { threshold: 0.5 }).observe(section);
  }
}
