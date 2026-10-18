// Presentation data only. These are synthetic examples, not captured Bloq runs.
// The first scenario follows the counts and conditions in the landing page handoff.

// Outcomes are ordered so the two expected Bell outcomes sit together under one bracket.
export const outcomeOrder = ["00", "11", "01", "10"];

// Every dimension Bloq compares: plain name first, technical term second.
// Plain names match the "usual suspects" in the problem section.
// `term` links the technical label to the glossary; `nameTerm` links a word in the plain name.
export const dimensions = [
  { key: "source", name: "The code", tile: "The code", tech: "Source & logical circuit" },
  { key: "compilation", name: "The translation", tile: "The translation", tech: "Compilation", term: "compilation" },
  { key: "footprint", name: "The qubits", tile: "The qubits", tech: "Physical footprint", nameTerm: { word: "qubits", term: "qubit" } },
  { key: "calibration", name: "The machine's condition", tile: "The machine", tech: "Calibration", term: "calibration" },
  { key: "counts", name: "The answers it gave", tile: "Chance", tech: "Counts" },
];

export const glossary = {
  qubit: "The quantum version of a bit. Real hardware has many, and they're not all equally good.",
  shots: "How many times the program was run. Quantum results are random, so you run it many times and count the answers.",
  calibration: "Measurements of how well the hardware is working right now. It drifts over hours.",
  compilation: "Translating your program into the specific operations a given machine can run.",
};

export const shots = 1000;
export const footnote = "Synthetic example. Bell circuit, FakeSherbrooke metadata.";
export const verdictLine = "Bloq doesn't judge whether this difference matters.";

// Per dimension, state is "unchanged" | "changed" | "unavailable".
// `recorded` is shown in the tooltip of the "What stayed the same" list.
// `culprit` names the suspect tile that gets the accent; `evidence` picks its evidence block.
const same = {
  source: { state: "unchanged", recorded: "Bell circuit · source and environment match" },
  compilation: { state: "unchanged", recorded: "Fixed seed · transpiler settings match" },
  footprint: { state: "unchanged", recorded: "Qubits 3, 4 in both runs" },
  calibration: { state: "unchanged", recorded: "Saved calibration metadata matches" },
};
const bell = { "00": 480, "01": 20, "10": 20, "11": 480 };

export const comparisonFixtures = {
  code: {
    label: "Someone edited the code",
    summary: "Someone changed one line, and the answers moved a lot.",
    culprit: "source",
    dimensions: { ...same, source: { state: "changed", from: "qc.cx(0, 1)", to: "qc.cx(1, 0)" }, counts: { state: "changed" } },
    counts: { baseline: { "00": 500, "01": 0, "10": 0, "11": 500 }, candidate: { "00": 500, "01": 500, "10": 0, "11": 0 } },
    chartCaption: "The first program should only answer 00 or 11. Each run asked 1,000 times.",
    result: "Counts differ. The source changed. Compilation settings, footprint and calibration match.",
  },
  qubits: {
    label: "Different qubits",
    summary: "Same code, but it ran on a different part of the chip.",
    culprit: "footprint",
    dimensions: { ...same, footprint: { state: "changed", from: "Qubits 3, 4", to: "Qubits 7, 8" }, counts: { state: "changed" } },
    counts: { baseline: bell, candidate: { "00": 455, "01": 40, "10": 45, "11": 460 } },
    result: "Counts differ. The physical qubits changed. Source, compilation settings and calibration snapshot match.",
  },
  machine: {
    label: "The machine drifted",
    summary: "Nothing in your code changed. The hardware got noisier since last time.",
    culprit: "calibration",
    dimensions: { ...same, calibration: { state: "changed", from: "Error rate 0.8%", to: "Error rate 1.6%" }, counts: { state: "changed" } },
    counts: { baseline: bell, candidate: { "00": 450, "01": 48, "10": 52, "11": 450 } },
    result: "Counts differ. The recorded error rate on the qubits used doubled. Source, compilation and footprint match.",
  },
  chance: {
    label: "Nothing else changed",
    summary: "Bloq found no other differences. Quantum results always vary a little.",
    culprit: null,
    dimensions: { ...same, counts: { state: "changed" } },
    counts: { baseline: bell, candidate: { "00": 460, "01": 30, "10": 30, "11": 480 } },
    result: "Counts differ. Source, compilation, footprint and calibration match.",
  },
  missing: {
    label: "Missing info",
    summary: "The answers differ, but one run didn't record the machine's condition.",
    culprit: null,
    dimensions: {
      ...same,
      calibration: { state: "unavailable", status: "Not recorded", recorded: "First run: saved metadata · Second run: not recorded" },
      counts: { state: "changed" },
    },
    counts: { baseline: bell, candidate: { "00": 465, "01": 35, "10": 30, "11": 470 } },
    note: "Calibration comparison is unavailable: the second run didn't record it.",
    result: "Counts differ. Source, compilation and footprint match. Calibration wasn't recorded for the second run.",
  },
};
