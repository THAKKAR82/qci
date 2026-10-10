// Presentation data only. These are synthetic examples, not captured QCI runs.
// The first fixture follows the counts and conditions in the landing page handoff.
export const outcomeOrder = ["00", "01", "10", "11"];

export const comparisonFixtures = {
  sampling: {
    label: "Sampling only",
    baseline: "Example baseline",
    candidate: "Example candidate",
    rows: {
      source: ["Same source / env · Bell circuit", "Same source / env · Bell circuit", "unchanged"],
      compilation: ["Same settings · fixed seed", "Same settings · fixed seed", "unchanged"],
      footprint: ["Same physical resources", "Same physical resources", "unchanged"],
      calibration: ["Same saved metadata", "Same saved metadata", "unchanged"],
    },
    counts: {
      baseline: { "00": 480, "01": 20, "10": 20, "11": 480 },
      candidate: { "00": 460, "01": 30, "10": 30, "11": 480 },
    },
    interpretation:
      "The sampled counts differ. The recorded source, compilation, footprint and calibration metadata match in this example. Statistical significance and regression are not assessed.",
  },
  compilation: {
    label: "Compilation",
    baseline: "Example baseline",
    candidate: "Example candidate",
    rows: {
      source: ["Same source / env · Bell circuit", "Same source / env · Bell circuit", "unchanged"],
      compilation: ["Optimization level 2", "Optimization level 3", "changed"],
      footprint: ["Qubits 103, 104 · 18 ECR", "Qubits 104, 105 · 16 ECR", "changed"],
      calibration: ["Resources 103, 104", "Resources 104, 105", "not-comparable"],
    },
    counts: {
      baseline: { "00": 480, "01": 20, "10": 20, "11": 480 },
      candidate: { "00": 430, "01": 40, "10": 40, "11": 490 },
    },
    interpretation:
      "Compilation and physical mapping differ alongside the sampled results. Calibration from different physical resources is not a like-for-like change. This comparison does not assign cause.",
  },
  missing: {
    label: "Missing metadata",
    baseline: "Example baseline",
    candidate: "Example candidate",
    rows: {
      source: ["Same source / env · Bell circuit", "Same source / env · Bell circuit", "unchanged"],
      compilation: ["Same settings · fixed seed", "Same settings · fixed seed", "unchanged"],
      footprint: ["Same physical resources", "Same physical resources", "unchanged"],
      calibration: ["Saved metadata present", "Metadata unavailable", "unavailable"],
    },
    counts: {
      baseline: { "00": 480, "01": 20, "10": 20, "11": 480 },
      candidate: { "00": 470, "01": 30, "10": 20, "11": 480 },
    },
    interpretation:
      "Calibration metadata is unavailable for the candidate. QCI cannot call that evidence unchanged. The sampled distributions differ; their significance and cause remain unknown.",
  },
};
