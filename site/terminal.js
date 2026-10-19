// "Try it." terminal demo: click a qci command, watch it type, then zoom onto what matters.
// The layouts mirror the real qci screens: the plain `qci run` output, the "Runs" and "Show run"
// browser panels, and the side-by-side BASELINE │ CANDIDATE compare view with qci's section names
// and field labels (src/qci/cli/render_compare.py). The run IDs, hashes and values are made up.
// TODO: swap in captured output from a real run once the interactive browser ships.

const section = document.querySelector(".demo");

if (section) {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const mobile = window.matchMedia("(max-width: 767px)");
  const TYPE_MS = 30;
  const TYPE_BUDGET_MS = 1400; // long commands type faster so no command takes more than ~1.4 s
  const LINE_MS = 60;
  const ZOOM_DELAY_MS = 400;
  const HOLD_MS = 2500;
  const ZOOM = 1.18;

  const RUN_A = "01M53RN4JD8M0J8K8EXZZ8WBEE";
  const RUN_B = "01M540PCBN5YP8GN6K1VWXYQDA";

  // A line is a list of [text, class] segments; `hi` marks the highlighted lines.
  const t = (text, cls = "") => [text, cls];
  const plain = (text, cls = "", hi = false) => ({ parts: [t(text, cls)], hi });
  const field = (label, value) => ({ parts: [t(`${label}:`.padEnd(13), "muted"), t(value)] });

  // Box-drawn panel like the qci browser: ┌ Title ─┐, rows, ├─┤, footer, └─┘.
  function panel(title, rows, footer, width) {
    const inner = width - 4;
    const pad = (s) => s + " ".repeat(Math.max(0, inner - [...s].length));
    const lines = [{ parts: [t(`┌ ${title} ${"─".repeat(Math.max(0, width - title.length - 4))}┐`, "frame")] }];
    for (const row of rows) {
      const text = row.parts.map((p) => p[0]).join("");
      lines.push({ parts: [t("│ ", "frame"), ...row.parts, t(" ".repeat(Math.max(0, inner - [...text].length))), t(" │", "frame")], hi: row.hi });
    }
    lines.push({ parts: [t(`├${"─".repeat(width - 2)}┤`, "frame")] });
    lines.push({ parts: [t("│ ", "frame"), t(pad(footer), "muted"), t(" │", "frame")] });
    lines.push({ parts: [t(`└${"─".repeat(width - 2)}┘`, "frame")] });
    return lines;
  }

  const COMMANDS = {
    run: {
      typed: "qci run examples/bell.py --backend fake_sherbrooke --seed 7",
      lines: [
        plain(RUN_B, "", true),
        { parts: [t("Run succeeded. Inspect it with: ", "muted"), t(`qci show ${RUN_B.slice(0, 12)}…`)], hi: true },
      ],
      callout: "Every run gets a record: the code, the settings, the hardware and the results.",
    },
    runs: {
      typed: "qci runs",
      lines: panel("Runs", [
        { parts: [t("RUN ID                      CREATED (UTC)        STATUS     WORKLOAD", "muted")] },
        { parts: [t("BACKEND                     COMMIT", "muted")] },
        { parts: [t(`${RUN_B}  2026-10-17 04:07:35  succeeded  bell`)], hi: true },
        { parts: [t("fake_sherbrooke             26b57305c3")], hi: true },
        { parts: [t(`${RUN_A}  2026-10-17 01:47:06  succeeded  bell`)], hi: true },
        { parts: [t("fake_sherbrooke             c507fae415")], hi: true },
        { parts: [t("01M53RG3Q6KGR4B9YWPE1MGERZ  2026-10-17 01:44:21  succeeded  bell")] },
        { parts: [t("fake_sherbrooke             c507fae415")] },
      ], "1-3/3  ↑/↓ PgUp/PgDn scroll • Backspace returns", 70),
      callout: "The same program, run twice. Let's see what's different.",
    },
    // A condensed version of the real `qci show` output: the same sections, one line each.
    show: {
      typed: `qci show ${RUN_B}`,
      lines: [
        { parts: [t(`Run ${RUN_B}`), t("   status: ", "muted"), t("succeeded", "ok")] },
        field("Workload", "bell · examples/bell.py · entrypoint: build"),
        field("Provenance", "git 26b57305c3 (main) · CPython 3.13.9 · qiskit 2.5.2"),
        field("Logical", "qubits=2 clbits=2 depth=3 size=4 two_qubit_gates=1"),
        field("Backend", "qiskit_ibm/fake_sherbrooke · 127 qubits · simulator"),
        field("Compilation", "optimization_level=2 · layout initial=[104, 103]"),
        field("Execution", "shots=1000 · BackendSamplerV2"),
        { ...field("Result", "00=480  11=480  01=20  10=20"), hi: true },
        field("Metrics", "logical_depth=3 · transpiled_depth=6 · two_qubit_gates=1"),
      ],
      callout: "Code, circuit, hardware and answers: everything about one run, in one place.",
    },
  };

  // `qci compare`: the side-by-side view. Each row is baseline │ candidate; `*` marks a changed field.
  const COL = 37;
  const cell = (text) => text.slice(0, COL).padEnd(COL);
  const header = (title, status) => ({ parts: [t(`  ${title}  `), t(`[${status}]`, status === "changed" ? "changed" : "muted")] });
  const diff = (name, a, b) => ({ parts: [t(cell(`* ${name}: ${a}`), "removed"), t(" │ ", "frame"), t(`* ${name}: ${b}`, "added")], hi: true });
  const missing = (text) => ({ parts: [t(cell(`  ${text}`), "muted"), t(" │ ", "frame"), t(`  ${text}`, "missing")], hi: true });

  const SCENARIOS = {
    code: {
      sections: [
        header("Source", "changed"),
        diff("source sha256", "651c4bec7af8…", "9a3e07d14b2c…"),
        diff("git commit", "26b57305c3", "c507fae415"),
        header("Logical circuit", "changed"),
        diff("two qubit edges", "0, 1", "1, 0"),
        header("Environment", "unchanged"),
        header("Compilation", "unchanged"),
        header("Hardware (footprint-scoped)", "unchanged"),
      ],
      tvd: "0.5",
      callout: "Found it. Someone changed the code, and the two-qubit gate flipped direction.",
    },
    qubits: {
      sections: [
        header("Source", "unchanged"),
        header("Compilation", "changed"),
        diff("initial layout", "104, 103", "7, 8"),
        diff("final layout", "104, 103", "7, 8"),
        header("Physical footprint", "changed"),
        diff("qubits", "103, 104", "7, 8"),
        header("Hardware (footprint-scoped)", "unchanged"),
      ],
      tvd: "0.045",
      callout: "Same code, different part of the chip.",
    },
    machine: {
      sections: [
        header("Source", "unchanged"),
        header("Compilation", "unchanged"),
        header("Backend", "changed"),
        diff("calibrated at", "2026-10-16 09:12", "2026-10-17 03:40"),
        header("Hardware (footprint-scoped)", "changed"),
        diff("relevant hardware changed", "False", "True"),
      ],
      tvd: "0.06",
      callout: "Your code didn't change. The hardware it ran on was recalibrated, and it got noisier.",
    },
    nothing: {
      sections: [
        header("Source", "unchanged"),
        header("Environment", "unchanged"),
        header("Logical circuit", "unchanged"),
        header("Compilation", "unchanged"),
        header("Execution", "unchanged"),
        header("Hardware (footprint-scoped)", "unchanged"),
      ],
      tvd: "0.02",
      highlightResult: true,
      callout: "Nothing else changed. Quantum results always vary a little.",
    },
    missing: {
      sections: [
        header("Source", "unchanged"),
        header("Compilation", "unchanged"),
        header("Hardware (footprint-scoped)", "unavailable"),
        missing("unavailable: candidate calibration"),
      ],
      tvd: "0.025",
      callout: "One run didn't save the machine's condition, so qci says it can't compare it.",
    },
  };

  function compareCommand(name) {
    const s = SCENARIOS[name];
    const lines = [
      { parts: [t(cell(`BASELINE ${RUN_A.slice(0, 12)}`)), t(" │ ", "frame"), t(`CANDIDATE ${RUN_B.slice(0, 12)}`)] },
      { parts: [t(`${"─".repeat(COL)}─┼─${"─".repeat(COL)}`, "frame")] },
      ...s.sections,
      header("Result distribution", "changed"),
      { parts: [t(`  tvd = ${s.tvd}`)], hi: Boolean(s.highlightResult) },
      { parts: [t("* changed  ↑/↓ PgUp/PgDn scroll  f expand/shrink", "muted")] },
    ];
    return { typed: `qci compare ${RUN_A.slice(0, 12)} ${RUN_B.slice(0, 12)}`, lines, callout: s.callout };
  }

  const buttons = [...section.querySelectorAll("[data-cmd]")];
  const chips = [...section.querySelectorAll("[data-scenario]")];
  const scenarioGroup = section.querySelector(".demo-scenarios");
  const viewport = section.querySelector(".term-viewport");
  const body = section.querySelector(".term-body");
  const live = section.querySelector("[data-term-live]");
  const callout = section.querySelector(".term-callout");
  const calloutText = callout.querySelector("[data-callout-text]");
  let scenario = "code";
  let token = 0;
  let autoPlayed = false;

  const wait = (ms, my) => new Promise((resolve, reject) => setTimeout(() => (my === token ? resolve() : reject(new Error("cancelled"))), ms));

  function lineElement(line) {
    const el = document.createElement("div");
    el.className = "term-line";
    for (const [text, cls] of line.parts) {
      const span = document.createElement("span");
      span.textContent = text;
      if (cls) span.className = `t-${cls}`;
      el.append(span);
    }
    if (line.hi) el.dataset.hi = "";
    return el;
  }

  function promptLine() {
    const el = document.createElement("div");
    el.className = "term-line term-prompt";
    el.innerHTML = '<span class="t-muted">$ </span><span class="term-typed"></span><span class="term-cursor" aria-hidden="true"></span>';
    return el;
  }

  function resetZoom() {
    body.style.transform = "";
    body.classList.remove("is-zoomed");
  }

  function showCallout(text, { small = false } = {}) {
    calloutText.textContent = text;
    callout.hidden = false;
    callout.classList.toggle("is-small", small);
  }

  function zoomTo(highlighted) {
    if (!highlighted.length || mobile.matches || reducedMotion.matches) return;
    const first = highlighted[0];
    const last = highlighted[highlighted.length - 1];
    const originY = (first.offsetTop + last.offsetTop + last.offsetHeight) / 2;
    body.style.transformOrigin = `0 ${originY}px`;
    body.classList.add("is-zoomed");
    body.style.transform = `scale(${ZOOM})`;
  }

  async function play(spec) {
    const my = ++token;
    resetZoom();
    callout.hidden = true;
    body.classList.add("is-clearing");
    if (!reducedMotion.matches) await wait(150, my);
    body.replaceChildren();
    body.classList.remove("is-clearing", "has-highlight");

    const prompt = promptLine();
    body.append(prompt);
    const typed = prompt.querySelector(".term-typed");
    if (reducedMotion.matches) typed.textContent = spec.typed;
    else {
      const perChar = Math.min(TYPE_MS, TYPE_BUDGET_MS / spec.typed.length);
      for (const char of spec.typed) { typed.textContent += char; await wait(perChar, my); }
    }
    prompt.querySelector(".term-cursor").remove();

    const lines = spec.lines.map(lineElement);
    for (const el of lines) {
      body.append(el);
      if (!reducedMotion.matches) await wait(LINE_MS, my);
    }
    const idle = promptLine();
    idle.querySelector(".term-typed").remove();
    body.append(idle);

    // Announce the final output once, not each character.
    live.textContent = `${spec.typed}. ${spec.lines.map((l) => l.parts.map((p) => p[0]).join("").replace(/[─│┌┐└┘├┤┼]/g, " ").replace(/\s+/g, " ").trim()).filter(Boolean).join(". ")}. ${spec.callout}`;

    body.classList.add("has-highlight");
    const highlighted = lines.filter((el) => el.hasAttribute("data-hi"));
    if (reducedMotion.matches) return showCallout(spec.callout);
    await wait(ZOOM_DELAY_MS, my);
    zoomTo(highlighted);
    showCallout(spec.callout);
    await wait(HOLD_MS, my);
    resetZoom();
    body.classList.remove("has-highlight");
    showCallout(spec.callout, { small: true });
  }

  // Guide people through the tour: once a command finishes, highlight the next one they haven't run
  // (run → runs → show → compare), then the compare scenarios they haven't tried.
  const ORDER = ["run", "runs", "show", "compare"];
  const playedCommands = new Set();
  const playedScenarios = new Set();

  function clearHint() {
    [...buttons, ...chips].forEach((el) => el.classList.remove("is-next"));
  }

  function suggestNext(cmd) {
    clearHint();
    const start = ORDER.indexOf(cmd);
    const nextCommand = [...ORDER.slice(start + 1), ...ORDER.slice(0, start)].find((c) => !playedCommands.has(c));
    if (nextCommand) {
      buttons.find((b) => b.dataset.cmd === nextCommand).classList.add("is-next");
      return;
    }
    // Every command has run: point at the next untried scenario (or back at compare to reach them).
    const nextChip = chips.find((c) => !playedScenarios.has(c.dataset.scenario));
    if (!nextChip) return;
    if (cmd === "compare") nextChip.classList.add("is-next");
    else buttons.find((b) => b.dataset.cmd === "compare").classList.add("is-next");
  }

  function select(cmd, { fromUser = true } = {}) {
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.cmd === cmd)));
    scenarioGroup.hidden = cmd !== "compare";
    if (fromUser) autoPlayed = true;
    clearHint();
    playedCommands.add(cmd);
    if (cmd === "compare") playedScenarios.add(scenario);
    const spec = cmd === "compare" ? compareCommand(scenario) : COMMANDS[cmd];
    play(spec).then(() => suggestNext(cmd)).catch(() => {});
  }

  buttons.forEach((b) => b.addEventListener("click", () => select(b.dataset.cmd)));
  chips.forEach((chip) => chip.addEventListener("click", () => {
    scenario = chip.dataset.scenario;
    chips.forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
    select("compare");
  }));

  // Idle prompt with a blinking cursor until something plays.
  body.append(promptLine());

  // Auto-play `qci compare` (Code edited) once, the first time the terminal is half visible.
  new IntersectionObserver(([entry], observer) => {
    if (entry.intersectionRatio < 0.5 || autoPlayed) return;
    observer.disconnect();
    autoPlayed = true;
    select("compare", { fromUser: false });
  }, { threshold: 0.5 }).observe(viewport);
}
