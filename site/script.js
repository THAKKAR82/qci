import { githubStars, siteLinks } from "./site-config.js";
import "./bloch-sphere.js";
import "./qubits.js";
import "./quotes.js";
import "./terminal.js";

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

// "Copy" buttons in the install boxes show "Copied" for 1.5 s.
for (const button of document.querySelectorAll(".copy-button")) {
  let reset;
  button.addEventListener("click", async () => {
    await copyText(button.dataset.copy);
    clearTimeout(reset);
    button.querySelector("[data-copy-label]").textContent = "Copied";
    copyStatus.textContent = `Copied: ${button.dataset.copy}`;
    reset = setTimeout(() => {
      button.querySelector("[data-copy-label]").textContent = "Copy";
      copyStatus.textContent = "";
    }, 1500);
  });
}

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

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
