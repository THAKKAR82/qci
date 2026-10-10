import { comparisonFixtures, outcomeOrder } from "./demo-fixtures.js";
import { contactConfig } from "./site-config.js";
import "./bloch-sphere.js";

const menuButton = document.querySelector(".menu-toggle");
const primaryNav = document.querySelector(".primary-nav");

function closeMenu() {
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.setAttribute("aria-label", "Open navigation");
  primaryNav.classList.remove("is-open");
}

menuButton.addEventListener("click", () => {
  const isOpen = menuButton.getAttribute("aria-expanded") === "true";
  menuButton.setAttribute("aria-expanded", String(!isOpen));
  menuButton.setAttribute("aria-label", isOpen ? "Open navigation" : "Close navigation");
  primaryNav.classList.toggle("is-open", !isOpen);
});
primaryNav.addEventListener("click", (event) => {
  if (event.target.closest("a")) closeMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMenu();
});

const stateLabels = {
  unchanged: "Unchanged",
  changed: "Changed",
  unavailable: "Unavailable",
  "not-comparable": "Not comparable",
};
const demoButtons = [...document.querySelectorAll("[data-demo]")];
const demo = document.querySelector(".demo");

function tvdFromCounts(baseline, candidate) {
  const baselineTotal = outcomeOrder.reduce((sum, outcome) => sum + baseline[outcome], 0);
  const candidateTotal = outcomeOrder.reduce((sum, outcome) => sum + candidate[outcome], 0);
  return outcomeOrder.reduce((sum, outcome) => {
    return sum + Math.abs(baseline[outcome] / baselineTotal - candidate[outcome] / candidateTotal);
  }, 0) / 2;
}

function selectDemo(name) {
  const fixture = comparisonFixtures[name];
  if (!fixture) return;

  demo.querySelector('[data-run="baseline"]').textContent = fixture.baseline;
  demo.querySelector('[data-run="candidate"]').textContent = fixture.candidate;

  for (const [field, [baseline, candidate, state]] of Object.entries(fixture.rows)) {
    const row = demo.querySelector(`[data-field="${field}"]`);
    row.querySelector(`[data-value="${field}-baseline"]`).textContent = baseline;
    row.querySelector(`[data-value="${field}-candidate"]`).textContent = candidate;
    row.dataset.observation = state;
    const label = row.querySelector("[data-state]");
    label.className = `evidence-state state-${state}`;
    const dot = document.createElement("span");
    dot.setAttribute("aria-hidden", "true");
    dot.textContent = "●";
    label.replaceChildren(dot, document.createTextNode(` ${stateLabels[state]}`));
  }

  for (const side of ["baseline", "candidate"]) {
    demo.querySelector(`[data-counts="${side}"]`).textContent = outcomeOrder
      .map((outcome) => fixture.counts[side][outcome])
      .join(" / ");
  }
  demo.querySelector("[data-tvd]").textContent = tvdFromCounts(
    fixture.counts.baseline,
    fixture.counts.candidate,
  ).toFixed(3);
  demo.querySelector("[data-interpretation]").textContent = fixture.interpretation;
  demoButtons.forEach((button) => {
    const active = button.dataset.demo === name;
    button.setAttribute("aria-pressed", String(active));
    button.classList.toggle("is-active", active);
  });
}

demoButtons.forEach((button) => {
  button.addEventListener("click", () => selectDemo(button.dataset.demo));
});
selectDemo("sampling");

const contactForm = document.querySelector("#contact-form");
const contactEmailOption = document.querySelector("#contact-email-option");
const contactPending = document.querySelector("#contact-pending");

if (contactConfig.endpoint) {
  contactForm.hidden = false;
  contactPending.hidden = true;
  const emailInput = contactForm.elements.email;
  const emailError = contactForm.querySelector("#email-error");
  const formStatus = contactForm.querySelector(".form-status");
  const submitButton = contactForm.querySelector('button[type="submit"]');

  function validateEmail() {
    const value = emailInput.value.trim();
    let message = "";
    if (!value) message = "Enter your email address.";
    else if (emailInput.validity.typeMismatch) message = "Enter a valid email address.";
    emailError.textContent = message;
    emailInput.setAttribute("aria-invalid", String(Boolean(message)));
    return !message;
  }

  emailInput.addEventListener("blur", validateEmail);
  emailInput.addEventListener("input", () => {
    if (emailInput.getAttribute("aria-invalid") === "true") validateEmail();
  });

  contactForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!validateEmail()) {
      emailInput.focus();
      return;
    }

    const fields = new FormData(contactForm);
    const payload = {
      email: String(fields.get("email") || "").trim(),
      name: String(fields.get("name") || "").trim(),
      team: String(fields.get("team") || "").trim(),
      message: String(fields.get("message") || "").trim(),
    };
    submitButton.disabled = true;
    submitButton.textContent = "Sending…";
    formStatus.className = "form-status";
    formStatus.textContent = "Sending your message…";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(contactConfig.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      const acknowledgement = await response.json();
      if (!response.ok || acknowledgement.received !== true) throw new Error("not acknowledged");
      formStatus.className = "form-status is-success";
      formStatus.textContent = "Message received. We’ll follow up by email.";
      contactForm.reset();
      submitButton.textContent = "Message sent";
    } catch {
      formStatus.className = "form-status is-error";
      formStatus.textContent = "Your message could not be sent. Please try again; your details are still here.";
      submitButton.textContent = "Send message ↗";
      submitButton.disabled = false;
    } finally {
      clearTimeout(timeout);
    }
  });
} else if (contactConfig.email) {
  contactEmailOption.hidden = false;
  contactPending.hidden = true;
  const emailLink = contactEmailOption.querySelector("#contact-email-link");
  emailLink.href = `mailto:${contactConfig.email}?subject=${encodeURIComponent("QCI workflow conversation")}`;
}
