import {
  comparisonFixtures,
  dimensions,
  footnote,
  glossary,
  outcomeOrder,
  shots,
  verdictLine,
} from "./demo-fixtures.js";
import { githubStars, siteLinks } from "./site-config.js";
import "./bloch-sphere.js";
import "./race.js";
import "./quotes.js";

// The star count stays hidden until a real number is configured.
if (typeof githubStars === "number") {
  const stars = document.querySelector("[data-stars]");
  stars.textContent = `★ ${new Intl.NumberFormat("en-US", { notation: "compact" }).format(githubStars)}`;
  stars.hidden = false;
}

for (const link of document.querySelectorAll("[data-link]")) {
  const href = siteLinks[link.dataset.link];
  if (href) link.href = href;
}

const menuButton = document.querySelector(".menu-toggle");
const navSheet = document.querySelector("#nav-sheet");
const desktopNav = window.matchMedia("(min-width: 768px)");

function setMenu(open) {
  menuButton.setAttribute("aria-expanded", String(open));
  menuButton.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  navSheet.hidden = !open;
}

menuButton.addEventListener("click", () => {
  setMenu(menuButton.getAttribute("aria-expanded") !== "true");
});
navSheet.addEventListener("click", (event) => {
  if (event.target.closest("a")) setMenu(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !navSheet.hidden) {
    setMenu(false);
    menuButton.focus();
  }
});
desktopNav.addEventListener("change", (event) => {
  if (event.matches) setMenu(false);
});

const copyStatus = document.querySelector("[data-copy-status]");

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.append(field);
    field.select();
    document.execCommand("copy");
    field.remove();
  }
}

// Text "Copy" buttons (install boxes) and icon-only command copy buttons share one handler.
const copyIcon = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5" /><path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" /></svg>';
const cliStatus = document.querySelector("[data-cli-status]");
document.querySelectorAll(".cli-copy").forEach((button) => { button.innerHTML = copyIcon; });

for (const button of document.querySelectorAll(".copy-button, .cli-copy")) {
  let reset;
  button.addEventListener("click", async () => {
    await copyText(button.dataset.copy);
    clearTimeout(reset);
    const iconOnly = button.classList.contains("cli-copy");
    const status = iconOnly ? cliStatus : copyStatus;
    // Command chips show a "Copied" tooltip; install boxes swap their label.
    if (iconOnly) button.dataset.copied = "";
    else button.querySelector("[data-copy-label]").textContent = "Copied";
    status.textContent = `Copied: ${button.dataset.copy}`;
    reset = setTimeout(() => {
      if (iconOnly) delete button.dataset.copied;
      else button.querySelector("[data-copy-label]").textContent = "Copy";
      status.textContent = "";
    }, 1500);
  });
}

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

// Example comparison.
const surface = document.querySelector(".cmp-surface");
const segmented = document.querySelector(".segmented");
const thumb = segmented.querySelector(".segmented-thumb");
const demoButtons = [...segmented.querySelectorAll("[data-demo]")];
const matchedToggle = document.querySelector(".matched-toggle");
const verdictSummary = document.querySelector("[data-verdict-summary]");
const tilesList = document.querySelector("[data-tiles]");
const regions = {
  changed: surface.querySelector("[data-changed]"),
  result: surface.querySelector("[data-result]"),
  matched: surface.querySelector("[data-matched]"),
  matchedCount: surface.querySelector("[data-matched-count]"),
};
const numberFormat = new Intl.NumberFormat("en-US");
const icons = {
  check: '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><path d="M3.5 8.5l3 3 6-7" /></svg>',
  dashed: '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><circle cx="8" cy="8" r="6" stroke-dasharray="2.4 2.4" /></svg>',
  unknown: '<span class="icon-unknown" aria-hidden="true">?</span>',
  dot: '<span class="changed-dot" aria-hidden="true"></span>',
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);
}

function termButton(word, term) {
  return `<button type="button" class="term" data-term="${term}">${escapeHtml(word)}</button>`;
}

function plainName(dimension) {
  const name = escapeHtml(dimension.name);
  if (!dimension.nameTerm) return name;
  const { word, term } = dimension.nameTerm;
  return name.replace(word, termButton(word, term));
}

function techLabel(dimension) {
  return dimension.term ? termButton(dimension.tech, dimension.term) : escapeHtml(dimension.tech);
}

function tvdFromCounts(baseline, candidate) {
  const total = (counts) => outcomeOrder.reduce((sum, outcome) => sum + counts[outcome], 0);
  const baselineTotal = total(baseline);
  const candidateTotal = total(candidate);
  return outcomeOrder.reduce((sum, outcome) => {
    return sum + Math.abs(baseline[outcome] / baselineTotal - candidate[outcome] / candidateTotal);
  }, 0) / 2;
}

function renderChart(counts, caption) {
  const captionText = caption ?? `This program should only answer 00 or 11. Each run asked ${numberFormat.format(shots)} times.`;
  const max = Math.max(...outcomeOrder.flatMap((outcome) => [counts.baseline[outcome], counts.candidate[outcome]]));
  const description = outcomeOrder
    .map((outcome) => `${outcome}: first run ${counts.baseline[outcome]}, second run ${counts.candidate[outcome]}`)
    .join("; ");
  const bar = (value, side) => `
    <div class="bar-col bar-col-${side}">
      <span class="bar-value">${numberFormat.format(value)}</span>
      <span class="bar" style="--h: ${(value / max).toFixed(4)}"></span>
    </div>`;
  const groups = outcomeOrder.map((outcome) => `
    <div class="bar-group">
      <div class="bars">${bar(counts.baseline[outcome], "a")}${bar(counts.candidate[outcome], "b")}</div>
      <span class="outcome">${outcome}</span>
    </div>`).join("");
  return `
    <figure class="chart">
      <div class="chart-brackets" aria-hidden="true">
        <div class="bracket"><span class="long">Expected answers</span><span class="short">Expected</span></div>
        <div class="bracket"><span class="long">Unexpected answers</span><span class="short">Unexpected</span></div>
      </div>
      <div class="chart-plot" role="img" aria-label="Answer counts per outcome. Expected answers 00 and 11, unexpected 01 and 10. ${description}.">${groups}</div>
      <figcaption class="chart-caption">${escapeHtml(captionText)}</figcaption>
    </figure>`;
}

function renderCompilation(fixture) {
  const byKey = Object.fromEntries(dimensions.map((dimension) => [dimension.key, dimension]));
  const stats = fixture.circuitStats.map((stat) => `
    <tr><th scope="row">${escapeHtml(stat.label)}</th><td>${escapeHtml(stat.from)} <span class="arrow" aria-label="to">→</span> ${escapeHtml(stat.to)}</td><td class="delta">${escapeHtml(stat.delta)}</td></tr>`).join("");
  const changeRow = (key, value) => `
    <div class="change-row">
      <dt>${plainName(byKey[key])} <span class="tech">${techLabel(byKey[key])}</span></dt>
      <dd>${value}</dd>
    </div>`;
  const counts = (side) => outcomeOrder.map((outcome) => `${outcome} ${fixture.counts[side][outcome]}`).join(" · ");
  const arrow = ' <span class="arrow" aria-label="to">→</span> ';
  return `
    <table class="stats">
      <caption class="col-label">Compiled circuit, first run → second run</caption>
      <tbody>${stats}</tbody>
    </table>
    <dl class="change-rows">
      ${["compilation", "footprint"]
        .filter((key) => fixture.dimensions[key].state === "changed")
        .map((key) => changeRow(key, `${escapeHtml(fixture.dimensions[key].from)}${arrow}${escapeHtml(fixture.dimensions[key].to)}`))
        .join("")}
      ${changeRow("counts", `${counts("baseline")}${arrow}${counts("candidate")}`)}
    </dl>`;
}

function renderChanged(fixture) {
  const changed = dimensions.filter((dimension) => fixture.dimensions[dimension.key].state === "changed");
  const items = changed.map((dimension) => `<li>${plainName(dimension)} <span class="tech">${techLabel(dimension)}</span></li>`).join("");
  const legend = fixture.circuitStats ? "" : `
    <ul class="legend">
      <li><span class="swatch swatch-a" aria-hidden="true"></span>First run · ${numberFormat.format(shots)} ${termButton("shots", "shots")}</li>
      <li><span class="swatch swatch-b" aria-hidden="true"></span>Second run · ${numberFormat.format(shots)} ${termButton("shots", "shots")}</li>
    </ul>`;
  const body = fixture.circuitStats ? renderCompilation(fixture) : renderChart(fixture.counts, fixture.chartCaption);
  const note = fixture.note ? `<p class="cmp-note">${escapeHtml(fixture.note)}</p>` : "";
  return `
    <div class="changed-head">
      <p class="col-label"><span class="changed-dot" aria-hidden="true"></span>What changed</p>
      ${legend}
    </div>
    <ul class="changed-items" aria-label="Changed">${items}</ul>
    ${body}
    ${note}`;
}

function renderResult(fixture) {
  const tvd = tvdFromCounts(fixture.counts.baseline, fixture.counts.candidate);
  return `
    <p class="col-label">How different the results are</p>
    <p class="result-number">${formatPercent(tvd)}</p>
    <p class="result-tvd">Empirical TVD ${tvd.toFixed(3)}</p>
    <p class="result-line">${escapeHtml(fixture.result)}</p>
    <p class="result-line">${escapeHtml(verdictLine)}</p>
    <p class="result-foot">${escapeHtml(footnote)}</p>`;
}

function renderMatched(fixture) {
  return dimensions
    .filter((dimension) => fixture.dimensions[dimension.key].state !== "changed")
    .map((dimension) => {
      const entry = fixture.dimensions[dimension.key];
      const same = entry.state === "unchanged";
      const status = same ? "" : `<span class="matched-status">${escapeHtml(entry.status)}</span>`;
      return `
        <li class="matched-row" tabindex="0" data-tip="${escapeHtml(entry.recorded)}">
          ${same ? icons.check : icons.dashed}
          <span class="matched-text">
            <span class="matched-name">${plainName(dimension)}</span>
            <span class="tech">${techLabel(dimension)}</span>
            ${status}
          </span>
        </li>`;
    })
    .join("");
}

// "What else changed?": four suspect tiles. The culprit gets the accent, double width and its evidence.
const SUSPECTS = dimensions.filter((dimension) => ["source", "compilation", "footprint", "calibration"].includes(dimension.key));
let tilesRevealed = reducedMotion.matches;
const effectBars = document.querySelector("[data-effect-bars]");
const effectNumber = document.querySelector("[data-effect-number]");

function formatPercent(fraction) {
  const value = Math.round(fraction * 1000) / 10;
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`;
}

function renderEffect(fixture) {
  const order = ["00", "01", "10", "11"];
  const { baseline, candidate } = fixture.counts;
  const max = Math.max(...order.flatMap((outcome) => [baseline[outcome], candidate[outcome]]));
  effectBars.innerHTML = order.map((outcome) => `
    <span class="effect-group">
      <span class="effect-pair" aria-hidden="true">
        <span class="effect-bar effect-bar-a" style="--h: ${(baseline[outcome] / max).toFixed(3)}"></span>
        <span class="effect-bar effect-bar-b" style="--h: ${(candidate[outcome] / max).toFixed(3)}"></span>
      </span>
      <span class="effect-outcome">${outcome}</span>
    </span>`).join("");
  effectBars.setAttribute("role", "img");
  effectBars.setAttribute("aria-label", `Answer counts, run 1 against run 2: ${order.map((o) => `${o} ${baseline[o]} and ${candidate[o]}`).join("; ")}.`);
  effectNumber.textContent = formatPercent(tvdFromCounts(baseline, candidate));
}

function evidence(fixture, key) {
  if (key === "source") {
    const { from, to } = fixture.dimensions.source;
    return `<pre class="ev-diff"><span class="ev-del">- ${escapeHtml(from)}</span>\n<span class="ev-add">+ ${escapeHtml(to)}</span></pre><p class="ev-caption">1 line edited</p>`;
  }
  if (key === "footprint") {
    const qubits = Array.from({ length: 12 }, (_, i) => {
      const role = [3, 4].includes(i) ? " is-run1" : [7, 8].includes(i) ? " is-run2" : "";
      return `<span class="ev-qubit${role}">${i}</span>`;
    }).join("");
    return `<div class="ev-chip" role="img" aria-label="Chip map: run 1 used qubits 3 and 4, run 2 used qubits 7 and 8.">${qubits}</div><p class="ev-caption">Ran on qubits 7 &amp; 8 instead of 3 &amp; 4</p>`;
  }
  if (key === "calibration") {
    return `<div class="ev-rates">
        <span class="ev-rate-label">Last run</span><span class="ev-rate"><span class="ev-rate-bar" style="--w: .5"></span></span><span class="ev-rate-value">0.8%</span>
        <span class="ev-rate-label">This run</span><span class="ev-rate"><span class="ev-rate-bar is-now" style="--w: 1"></span></span><span class="ev-rate-value">1.6%</span>
      </div><p class="ev-caption">Recorded error rate doubled</p>`;
  }
  return "";
}

function tileModel(fixture, dimension) {
  const entry = fixture.dimensions[dimension.key];
  if (fixture.culprit === dimension.key) {
    return { state: "culprit", html: `<span class="tile-status">${icons.dot}<span class="tile-word">Changed</span></span><div class="tile-evidence">${evidence(fixture, dimension.key)}</div>` };
  }
  if (entry.state === "unavailable") {
    return { state: "missing", html: `<span class="tile-status">${icons.unknown}<span class="tile-word">Not recorded</span></span><span class="tile-fact">Can't compare</span>` };
  }
  return { state: "same", html: `<span class="tile-status">${icons.check}<span class="tile-word">Same</span></span>` };
}

const pendingTile = `<span class="tile-status">${icons.unknown}<span class="tile-word">Checking</span></span>`;

function swapTile(tile, next, delay) {
  if (tile.dataset.state === next.state && tile.dataset.html === next.html) return;
  const apply = () => {
    tile.dataset.state = next.state;
    tile.dataset.html = next.html;
    tile.querySelector(".tile-body").innerHTML = next.html;
    tile.classList.remove("is-fading");
  };
  if (reducedMotion.matches) return apply();
  setTimeout(() => {
    tile.classList.add("is-fading");
    setTimeout(apply, 125);
  }, delay);
}

function layoutTiles(fixture) {
  // The culprit column is 2fr, the rest 1fr; with no culprit all four are equal. Animated in CSS.
  tilesList.style.gridTemplateColumns = SUSPECTS.map((dimension) => (fixture.culprit === dimension.key ? "2fr" : "1fr")).join(" ");
}

function renderTiles(fixture) {
  if (!tilesList.children.length) {
    tilesList.innerHTML = SUSPECTS.map((dimension) => `
      <li class="tile" data-state="pending"><span class="tile-name">${escapeHtml(dimension.tile)}</span><span class="tile-body">${pendingTile}</span></li>`).join("");
  }
  renderEffect(fixture);
  if (!tilesRevealed) return;
  layoutTiles(fixture);
  [...tilesList.children].forEach((tile, index) => swapTile(tile, tileModel(fixture, SUSPECTS[index]), 0));
}

function revealTiles() {
  tilesRevealed = true;
  const fixture = comparisonFixtures[segmented.querySelector('[aria-pressed="true"]').dataset.demo];
  layoutTiles(fixture);
  [...tilesList.children].forEach((tile, index) => swapTile(tile, tileModel(fixture, SUSPECTS[index]), index * 150));
}

function render(name) {
  const fixture = comparisonFixtures[name];
  const identical = dimensions.filter((dimension) => fixture.dimensions[dimension.key].state === "unchanged").length;
  verdictSummary.textContent = fixture.summary;
  renderTiles(fixture);
  regions.changed.innerHTML = renderChanged(fixture);
  regions.result.innerHTML = renderResult(fixture);
  regions.matched.innerHTML = renderMatched(fixture);
  regions.matchedCount.textContent = `${identical} of ${dimensions.length} dimensions identical`;
}

function moveThumb() {
  const active = segmented.querySelector('[aria-pressed="true"]');
  thumb.style.width = `${active.offsetWidth}px`;
  thumb.style.height = `${active.offsetHeight}px`;
  thumb.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop}px)`;
}

let switchTimer;
function selectDemo(name) {
  if (!comparisonFixtures[name]) return;
  demoButtons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.demo === name)));
  moveThumb();
  hidePopover();
  clearTimeout(switchTimer);
  verdictSummary.textContent = comparisonFixtures[name].summary;
  renderTiles(comparisonFixtures[name]);
  if (reducedMotion.matches) {
    render(name);
    return;
  }
  surface.classList.add("is-switching");
  switchTimer = setTimeout(() => {
    render(name);
    surface.classList.remove("is-switching");
  }, 200);
}

demoButtons.forEach((button) => {
  button.addEventListener("click", () => selectDemo(button.dataset.demo));
});
matchedToggle.addEventListener("click", () => {
  matchedToggle.setAttribute("aria-expanded", String(matchedToggle.getAttribute("aria-expanded") !== "true"));
});
new ResizeObserver(moveThumb).observe(segmented);
render("code");
moveThumb();

// Tiles resolve left to right the first time they scroll into view.
if (!tilesRevealed) {
  new IntersectionObserver(([entry], observer) => {
    if (!entry.isIntersecting) return;
    observer.disconnect();
    revealTiles();
  }, { threshold: 0.5 }).observe(tilesList);
}

// "Show the data": the detailed view, collapsed by default.
const disclosure = document.querySelector(".cmp-disclosure");
const details = document.querySelector("#cmp-details");
disclosure.addEventListener("click", () => {
  const open = disclosure.getAttribute("aria-expanded") !== "true";
  disclosure.setAttribute("aria-expanded", String(open));
  disclosure.firstChild.textContent = open ? "Hide the data " : "Show the data ";
  disclosure.querySelector("span").textContent = open ? "↑" : "↓";
  details.classList.toggle("is-open", open);
  details.inert = !open;
  if (open) moveThumb();
});

// One shared popover serves both glossary terms and recorded-value tooltips.
// Mouse hover and keyboard focus show it; a tap or click pins it; Escape or an outside tap dismisses it.
const popover = document.createElement("div");
popover.className = "popover";
popover.id = "popover";
popover.setAttribute("role", "tooltip");
popover.hidden = true;
document.body.append(popover);
let popoverTrigger = null;
let popoverMode = null;

function popoverTarget(node) {
  return node instanceof Element ? node.closest("[data-term], [data-tip]") : null;
}

function showPopover(trigger, mode) {
  if (popoverTrigger && popoverTrigger !== trigger) popoverTrigger.removeAttribute("aria-describedby");
  const term = trigger.dataset.term;
  if (term) {
    popover.innerHTML = `<strong>${escapeHtml(term)}</strong>${escapeHtml(glossary[term])}`;
  } else {
    popover.textContent = trigger.dataset.tip;
  }
  popover.hidden = false;
  trigger.setAttribute("aria-describedby", popover.id);
  popoverTrigger = trigger;
  popoverMode = mode;

  const rect = trigger.getBoundingClientRect();
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;
  const left = Math.min(Math.max(rect.left + rect.width / 2 - width / 2, 16), window.innerWidth - width - 16);
  const below = rect.bottom + 8;
  const top = below + height > window.innerHeight - 8 && rect.top - height - 8 > 0 ? rect.top - height - 8 : below;
  popover.style.left = `${left + window.scrollX}px`;
  popover.style.top = `${top + window.scrollY}px`;
}

function hidePopover() {
  if (popoverTrigger) popoverTrigger.removeAttribute("aria-describedby");
  popover.hidden = true;
  popoverTrigger = null;
  popoverMode = null;
}

document.addEventListener("pointerover", (event) => {
  if (event.pointerType !== "mouse") return;
  const trigger = popoverTarget(event.target);
  if (trigger && (trigger !== popoverTrigger || popoverMode !== "pinned")) showPopover(trigger, "hover");
});
document.addEventListener("pointerout", (event) => {
  if (event.pointerType !== "mouse" || popoverMode !== "hover") return;
  const next = popoverTarget(event.relatedTarget);
  if (!next) hidePopover();
});
document.addEventListener("focusin", (event) => {
  const trigger = popoverTarget(event.target);
  if (trigger && popoverMode !== "pinned") showPopover(trigger, "focus");
});
document.addEventListener("focusout", (event) => {
  if (popoverMode === "focus" && event.target === popoverTrigger && !popoverTarget(event.relatedTarget)) hidePopover();
});
document.addEventListener("click", (event) => {
  const trigger = popoverTarget(event.target);
  if (!trigger) {
    if (!popover.contains(event.target)) hidePopover();
    return;
  }
  if (trigger === popoverTrigger && popoverMode === "pinned") hidePopover();
  else showPopover(trigger, "pinned");
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !popover.hidden) hidePopover();
});
window.addEventListener("resize", hidePopover);

// Explainers ("What's this?" on the sphere, "Who is this?" on the portrait).
// Popover on desktop: hover (150 ms delay) or keyboard focus opens it, a click pins it, and it
// closes 200 ms after the pointer leaves, on Escape, on blur or on an outside click.
// Under 768px it becomes a bottom sheet with a backdrop, a close button and swipe-down to close.
const sheetMedia = window.matchMedia("(max-width: 767px)");
const hoverMedia = window.matchMedia("(hover: hover) and (pointer: fine)");

function setupExplainer({ trigger, panel, backdrop, placement = "above", onLink }) {
  const close = panel.querySelector(".sheet-close");
  const link = panel.querySelector("a");
  let openedBy = null;
  let openTimer;
  let closeTimer;
  let hideTimer;
  const isSheet = () => sheetMedia.matches;

  function open(source) {
    clearTimeout(closeTimer);
    clearTimeout(hideTimer);
    if (openedBy) {
      if (source !== "hover") openedBy = source;
      return;
    }
    openedBy = source;
    trigger.setAttribute("aria-expanded", "true");
    const sheet = isSheet();
    if (sheet) panel.setAttribute("aria-modal", "true");
    else panel.removeAttribute("aria-modal");
    panel.classList.toggle("is-below", placement === "below");
    panel.style.removeProperty("--drag");
    panel.hidden = false;
    backdrop.hidden = !sheet;
    if (!sheet && placement === "above") {
      // Flip below the trigger when there is no room above (e.g. under the sticky header).
      const headerBottom = document.querySelector(".site-header").getBoundingClientRect().bottom;
      if (panel.getBoundingClientRect().top < headerBottom + 8) panel.classList.add("is-below");
    }
    void panel.offsetWidth;
    panel.classList.add("is-open");
    backdrop.classList.add("is-open");
    if (sheet) close.focus();
  }

  function hide({ returnFocus = false } = {}) {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    if (!openedBy) return;
    const wasSheet = isSheet();
    openedBy = null;
    trigger.setAttribute("aria-expanded", "false");
    panel.classList.remove("is-open", "is-dragging");
    backdrop.classList.remove("is-open");
    hideTimer = setTimeout(() => {
      panel.hidden = true;
      backdrop.hidden = true;
    }, wasSheet ? 240 : 150);
    if (returnFocus || wasSheet) trigger.focus({ preventScroll: true });
  }

  for (const element of [trigger, panel]) {
    element.addEventListener("pointerenter", (event) => {
      if (event.pointerType !== "mouse" || !hoverMedia.matches || isSheet()) return;
      clearTimeout(closeTimer);
      if (!openedBy && element === trigger) openTimer = setTimeout(() => open("hover"), 150);
    });
    element.addEventListener("pointerleave", (event) => {
      if (event.pointerType !== "mouse") return;
      clearTimeout(openTimer);
      if (openedBy === "hover") closeTimer = setTimeout(() => hide(), 200);
    });
  }

  trigger.addEventListener("focus", () => {
    // Keyboard focus opens the popover; a tap's focus is left to the click handler.
    if (trigger.matches(":focus-visible") && !isSheet()) open("focus");
  });
  trigger.addEventListener("click", () => {
    if (openedBy && openedBy !== "hover") hide();
    else open("click");
  });
  trigger.addEventListener("blur", (event) => {
    if (isSheet() || !openedBy) return;
    if (!panel.contains(event.relatedTarget)) hide();
  });
  panel.addEventListener("focusout", (event) => {
    if (isSheet() || !openedBy) return;
    const next = event.relatedTarget;
    if (next !== trigger && !panel.contains(next)) hide();
  });
  close.addEventListener("click", () => hide({ returnFocus: true }));
  backdrop.addEventListener("click", () => hide({ returnFocus: true }));
  if (link && onLink) {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      hide();
      onLink();
    });
  }
  document.addEventListener("pointerdown", (event) => {
    if (!openedBy || panel.contains(event.target) || trigger.contains(event.target)) return;
    hide();
  });
  document.addEventListener("keydown", (event) => {
    if (!openedBy) return;
    if (event.key === "Escape") {
      hide({ returnFocus: panel.contains(document.activeElement) || document.activeElement === trigger });
      return;
    }
    // Keep keyboard focus inside the bottom sheet while it is open.
    if (event.key === "Tab" && isSheet()) {
      const focusable = [close, link].filter(Boolean);
      const index = focusable.indexOf(document.activeElement);
      event.preventDefault();
      const step = event.shiftKey ? -1 : 1;
      focusable[(index + step + focusable.length) % focusable.length].focus();
    }
  });
  sheetMedia.addEventListener("change", () => hide());

  // Swipe the sheet down to close it.
  let dragStart = null;
  panel.addEventListener("pointerdown", (event) => {
    if (!isSheet() || event.target.closest("a, button")) return;
    dragStart = event.clientY;
    panel.classList.add("is-dragging");
    panel.setPointerCapture(event.pointerId);
  });
  panel.addEventListener("pointermove", (event) => {
    if (dragStart === null) return;
    panel.style.setProperty("--drag", `${Math.max(0, event.clientY - dragStart)}px`);
  });
  const endDrag = (event) => {
    if (dragStart === null) return;
    const distance = event.clientY - dragStart;
    dragStart = null;
    panel.classList.remove("is-dragging");
    if (distance > 80) hide();
    else panel.style.removeProperty("--drag");
  };
  panel.addEventListener("pointerup", endDrag);
  panel.addEventListener("pointercancel", endDrag);
}

setupExplainer({
  trigger: document.querySelector(".sphere-help-trigger"),
  panel: document.querySelector("#sphere-help"),
  backdrop: document.querySelector(".sphere-help-backdrop"),
  placement: "above",
  onLink: () => document.querySelector("#problem").scrollIntoView({ behavior: reducedMotion.matches ? "auto" : "smooth" }),
});
setupExplainer({
  trigger: document.querySelector(".who-trigger"),
  panel: document.querySelector("#who-help"),
  backdrop: document.querySelector(".who-help-backdrop"),
  placement: "below",
});

// One-time hint under the sphere: first load of the session only.
const sphereHint = document.querySelector(".sphere-hint");
const sphereVisual = document.querySelector(".bloch-visual");
let hintSeen = false;
try {
  hintSeen = sessionStorage.getItem("bloq-sphere-hint") === "1";
  sessionStorage.setItem("bloq-sphere-hint", "1");
} catch {
  // Storage can be unavailable; the hint then shows on every load.
}
if (!hintSeen) {
  sphereHint.textContent = hoverMedia.matches
    ? "Point at the sphere to move its arrow"
    : "Touch the sphere to move its arrow";
  sphereHint.hidden = false;
  const dismissHint = () => {
    sphereHint.classList.add("is-fading");
    setTimeout(() => { sphereHint.hidden = true; }, reducedMotion.matches ? 0 : 400);
    sphereVisual.removeEventListener("pointerdown", dismissHint);
    sphereVisual.removeEventListener("pointermove", dismissHint);
  };
  // Passive listeners on the container only observe; the canvas still receives every event.
  sphereVisual.addEventListener("pointerdown", dismissHint, { passive: true });
  sphereVisual.addEventListener("pointermove", dismissHint, { passive: true });
  setTimeout(dismissHint, 6000);
}
