# M1.5d calibration history: results

This file is the verbatim `results.md` written by the M1.5d analysis script
(`experiments/calibration_history/run_analysis.py`, run once on 2026-10-19 from a clean tree at
commit `5ba0d8e`, store unchanged). Only this paragraph was added. It contains aggregates only:
counts, hours between provider dates or stamps, and dimensionless statistics. No calibration
parameter value appears (how this was checked: [design, Results](2026-10-calibration-history.md#results)).
Interpretation is in the design's Discussion section, not here.

Method `qci.m15d.analysis.1`; every number is `calculated`.
Collection date D = 2026-10-19; E_d = 2026-10-19T00:00:00+00:00; E_s = 2026-10-19T00:00:00+00:00.

## Provenance

| Field | Value |
|---|---|
| git commit | 5ba0d8e3d974c708b8034cc1ace5593e14743157 |
| git dirty | no |
| store SHA-256 before | 9be8d4bd12e9cfac29b3e5f66ab94dcb38ff557ec665becfa790246c6e205b1b |
| store SHA-256 after | 9be8d4bd12e9cfac29b3e5f66ab94dcb38ff557ec665becfa790246c6e205b1b |
| store unchanged | yes |

## Predictions

| Prediction | ibm_fez | ibm_kingston | ibm_marrakesh | Overall |
|---|---|---|---|---|
| P1 | supported | supported | supported | supported |
| P2 | supported | supported | supported | supported |
| P3 | at or above 0.5 | below 0.5 | at or above 0.5 | not supported |
| P4 | supported | supported | supported | supported |

P3 overall: not supported. Beside it, P(tau-b < 0.5) under a uniformly random relative ordering of 5 untied qubits: 106/120 = 0.8833. Interpretation only (2026-10-18, before collection): under a uniformly random relative ordering of 5 untied qubits, P(tau-b < 0.5) = 106/120, about 0.88. A 'supported' P3 is therefore weak evidence of rank instability; 'not supported' is the more informative outcome. Not used for marking.

### P1

| Device | distinct_documents | qubits_with_defined_cv | median_cv |
|---|---|---|---|
| ibm_fez | 142 | 5 | 0.1857 |
| ibm_kingston | 157 | 5 | 0.2199 |
| ibm_marrakesh | 151 | 5 | 0.2697 |

### P2

| Device | distinct_documents | qubits_with_defined_ratio | qubits_with_ratio_at_least_3 | largest_ratio |
|---|---|---|---|---|
| ibm_fez | 142 | 5 | 5 | 74.75 |
| ibm_kingston | 157 | 5 | 5 | 46.55 |
| ibm_marrakesh | 151 | 5 | 5 | 47.3 |

### P3

| Device | distinct_documents_g0_to_g6 | tau_b | n | same_document | resources_with_same_date | random_order_probability_below_0.5 |
|---|---|---|---|---|---|---|
| ibm_fez | 7 | 0.7379 | 5 | no | 0 | undefined: ties |
| ibm_kingston | 7 | 0.4 | 5 | no | 0 | 106/120 = 0.8833 |
| ibm_marrakesh | 7 | 0.6 | 5 | no | 0 | 106/120 = 0.8833 |

### P4

| Device | distinct_documents | pairs_with_numeric_value | nonzero_values | pairs_with_both_dates | fraction_date_equals_stamp |
|---|---|---|---|---|---|
| ibm_fez | 213 | 1065 | 0 | 1065 | 1 |
| ibm_kingston | 226 | 1130 | 0 | 1130 | 1 |
| ibm_marrakesh | 222 | 1110 | 0 | 1110 | 1 |

## ibm_fez

### Sets

| Set | grid_times | lookups_present | missing_grid_times | distinct_documents | documents_without_stamp | stamp_ties | documents_with_unusable_in_scope_series | requested - stamp, median h | max h |
|---|---|---|---|---|---|---|---|---|---|
| dense | 169 | 169 | 0 | 142 | 0 | 6 | 0 | 0.4894 | 15.49 |
| sparse | 73 | 73 | 0 | 73 | 0 | 0 | 57 | 0.5781 | 68.63 |

| Set | missing_row | duplicate_rows | null_value | non_numeric_value | non_finite_value | missing_date |
|---|---|---|---|---|---|---|
| dense | 0 | 0 | 0 | 0 | 0 | 0 |
| sparse | 285 | 0 | 0 | 0 | 0 | 0 |

### Dense: per-parameter medians over footprint resources

| Parameter | resources | median CV | (defined) | median max/min | (defined) | median d/m | (defined) |
|---|---|---|---|---|---|---|---|
| T1 | 5 | 0.1857 | 5 | 1.776 | 5 | 0.1695 | 5 |
| T2 | 5 | 0.2279 | 5 | 2.089 | 5 | 0.1936 | 5 |
| readout_error | 5 | 1.576 | 5 | 59.82 | 5 | 0.6049 | 5 |
| prob_meas0_prep1 | 5 | 1.552 | 5 | 47.24 | 5 | 0.563 | 5 |
| prob_meas1_prep0 | 5 | 1.662 | 5 | 198 | 4 | 0.6196 | 5 |
| init_error | 5 | 1.4 | 4 | 130.1 | 4 | 0.7169 | 4 |
| sx gate_error | 5 | 0.182 | 5 | 1.883 | 5 | 0.1669 | 5 |
| measure gate_error | 5 | 1.576 | 5 | 59.82 | 5 | 0.6049 | 5 |
| cz gate_error | 5 | 0.2154 | 5 | 1.883 | 5 | 0.1886 | 5 |

### Dense: per series

| Resource | Parameter | n | unavailable | not_re_measured | revised_same_date | re_measured_same_value | re_measured_different_value | date_earlier | interval median h | CV | max/min | d/m |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qubit/136 | T1 | 7 | 0 | 135 | 0 | 0 | 6 | 0 | 24.54 | 0.2746 | 2.434 | 0.1377 |
| qubit/141 | T1 | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.48 | 0.1579 | 1.776 | 0.146 |
| qubit/142 | T1 | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.48 | 0.1857 | 1.898 | 0.1695 |
| qubit/143 | T1 | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.48 | 0.2047 | 1.672 | 0.1886 |
| qubit/144 | T1 | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.48 | 0.1579 | 1.416 | 0.192 |
| qubit/136 | T2 | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.48 | 0.302 | 2.213 | 0.3157 |
| qubit/141 | T2 | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.48 | 0.122 | 1.474 | 0.1102 |
| qubit/142 | T2 | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.48 | 0.2279 | 2.089 | 0.1936 |
| qubit/143 | T2 | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.48 | 0.2544 | 2.313 | 0.2175 |
| qubit/144 | T2 | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.48 | 0.1543 | 1.538 | 0.1798 |
| qubit/136 | readout_error | 46 | 0 | 96 | 0 | 0 | 45 | 0 | 1.53 | 1.715 | 72.2 | 0.609 |
| qubit/141 | readout_error | 46 | 0 | 96 | 0 | 2 | 43 | 0 | 1.53 | 1.5 | 33.91 | 0.5533 |
| qubit/142 | readout_error | 46 | 0 | 96 | 0 | 0 | 45 | 0 | 1.53 | 1.576 | 47.44 | 0.568 |
| qubit/143 | readout_error | 46 | 0 | 96 | 0 | 1 | 44 | 0 | 1.53 | 1.705 | 74.75 | 0.6049 |
| qubit/144 | readout_error | 46 | 0 | 96 | 0 | 0 | 45 | 0 | 1.53 | 1.519 | 59.82 | 0.6093 |
| qubit/136 | prob_meas0_prep1 | 46 | 0 | 96 | 0 | 1 | 44 | 0 | 1.53 | 1.023 | 10.5 | 0.3418 |
| qubit/141 | prob_meas0_prep1 | 46 | 0 | 96 | 0 | 1 | 44 | 0 | 1.53 | 1.21 | 16.94 | 0.4783 |
| qubit/142 | prob_meas0_prep1 | 46 | 0 | 96 | 0 | 4 | 41 | 0 | 1.53 | 1.573 | 47.24 | 0.563 |
| qubit/143 | prob_meas0_prep1 | 46 | 0 | 96 | 0 | 0 | 45 | 0 | 1.53 | 1.685 | 72.31 | 0.6059 |
| qubit/144 | prob_meas0_prep1 | 46 | 0 | 96 | 0 | 2 | 43 | 0 | 1.53 | 1.552 | 51.75 | 0.6249 |
| qubit/136 | prob_meas1_prep0 | 46 | 0 | 96 | 0 | 2 | 43 | 0 | 1.53 | 1.842 | 459.7 | 0.6632 |
| qubit/141 | prob_meas1_prep0 | 46 | 0 | 96 | 0 | 1 | 44 | 0 | 1.53 | 1.662 | 129.7 | 0.6135 |
| qubit/142 | prob_meas1_prep0 | 46 | 0 | 96 | 0 | 1 | 44 | 0 | 1.53 | 1.604 | 194 | 0.6285 |
| qubit/143 | prob_meas1_prep0 | 46 | 0 | 96 | 0 | 7 | 38 | 0 | 1.53 | 1.792 | undefined: non_positive_minimum | 0.6158 |
| qubit/144 | prob_meas1_prep0 | 46 | 0 | 96 | 0 | 0 | 45 | 0 | 1.53 | 1.428 | 202 | 0.6196 |
| qubit/136 | init_error | 36 | 0 | 106 | 0 | 0 | 35 | 0 | 2.658 | 0.3957 | 6.003 | 0.4019 |
| qubit/141 | init_error | 1 | 0 | 141 | 0 | 0 | 0 | 0 | - | undefined: too_few_measurements | undefined: too_few_measurements | undefined: too_few_measurements |
| qubit/142 | init_error | 50 | 0 | 92 | 0 | 1 | 48 | 0 | 1.73 | 2.033 | 240.2 | 0.7672 |
| qubit/143 | init_error | 42 | 0 | 100 | 0 | 0 | 41 | 0 | 2.67 | 0.7677 | 20.02 | 0.6667 |
| qubit/144 | init_error | 46 | 0 | 96 | 0 | 0 | 45 | 0 | 2.617 | 2.395 | 243.9 | 1.321 |
| gate/sx/136 | gate_error | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.67 | 0.156 | 1.611 | 0.1341 |
| gate/sx/141 | gate_error | 7 | 0 | 135 | 0 | 0 | 6 | 0 | 24.57 | 0.2349 | 1.899 | 0.1669 |
| gate/sx/142 | gate_error | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.67 | 0.1596 | 1.737 | 0.1455 |
| gate/sx/143 | gate_error | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.67 | 0.182 | 1.883 | 0.1769 |
| gate/sx/144 | gate_error | 6 | 0 | 136 | 0 | 0 | 5 | 0 | 24.67 | 0.2318 | 2.066 | 0.2552 |
| gate/measure/136 | gate_error | 46 | 0 | 96 | 0 | 0 | 45 | 0 | 1.53 | 1.715 | 72.2 | 0.609 |
| gate/measure/141 | gate_error | 46 | 0 | 96 | 0 | 2 | 43 | 0 | 1.53 | 1.5 | 33.91 | 0.5533 |
| gate/measure/142 | gate_error | 46 | 0 | 96 | 0 | 0 | 45 | 0 | 1.53 | 1.576 | 47.44 | 0.568 |
| gate/measure/143 | gate_error | 46 | 0 | 96 | 0 | 1 | 44 | 0 | 1.53 | 1.705 | 74.75 | 0.6049 |
| gate/measure/144 | gate_error | 46 | 0 | 96 | 0 | 0 | 45 | 0 | 1.53 | 1.519 | 59.82 | 0.6093 |
| gate/cz/142,141 | gate_error | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.89 | 0.2154 | 1.883 | 0.1886 |
| gate/cz/142,143 | gate_error | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.89 | 0.1502 | 1.568 | 0.1126 |
| gate/cz/143,136 | gate_error | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.89 | 0.5168 | 3.98 | 0.4414 |
| gate/cz/143,142 | gate_error | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.89 | 0.1502 | 1.568 | 0.1126 |
| gate/cz/143,144 | gate_error | 8 | 0 | 134 | 0 | 0 | 7 | 0 | 24.89 | 0.2476 | 1.99 | 0.2295 |

### Sparse: per series

| Resource | Parameter | n | CV | max/min | d/m |
|---|---|---|---|---|---|
| qubit/136 | T1 | 73 | 0.2488 | 4.139 | 0.2286 |
| qubit/141 | T1 | 73 | 0.3065 | 5.842 | 0.2601 |
| qubit/142 | T1 | 73 | 0.2372 | 3.097 | 0.257 |
| qubit/143 | T1 | 73 | 0.2586 | 3.138 | 0.2579 |
| qubit/144 | T1 | 73 | 0.2263 | 3.703 | 0.2235 |
| qubit/136 | T2 | 73 | 0.2681 | 5.757 | 0.2785 |
| qubit/141 | T2 | 73 | 0.204 | 4.295 | 0.1843 |
| qubit/142 | T2 | 73 | 0.2295 | 2.969 | 0.2284 |
| qubit/143 | T2 | 73 | 0.2532 | 6.769 | 0.2536 |
| qubit/144 | T2 | 73 | 0.2766 | 7.07 | 0.2694 |
| qubit/136 | readout_error | 73 | 0.4075 | 6.192 | 0.3357 |
| qubit/141 | readout_error | 73 | 0.5636 | 10.67 | 0.5274 |
| qubit/142 | readout_error | 73 | 0.6777 | 11.54 | 0.6915 |
| qubit/143 | readout_error | 73 | 0.575 | 10.55 | 0.5395 |
| qubit/144 | readout_error | 73 | 0.9559 | 27.88 | 0.7634 |
| qubit/136 | prob_meas0_prep1 | 73 | 0.4053 | 5.913 | 0.3514 |
| qubit/141 | prob_meas0_prep1 | 73 | 0.6852 | 14.35 | 0.6756 |
| qubit/142 | prob_meas0_prep1 | 73 | 0.7742 | 16 | 0.8036 |
| qubit/143 | prob_meas0_prep1 | 73 | 0.6365 | 11.5 | 0.5607 |
| qubit/144 | prob_meas0_prep1 | 73 | 0.6902 | 19.67 | 0.565 |
| qubit/136 | prob_meas1_prep0 | 73 | 0.8547 | undefined: non_positive_minimum | 0.6633 |
| qubit/141 | prob_meas1_prep0 | 73 | 0.7694 | undefined: non_positive_minimum | 0.6604 |
| qubit/142 | prob_meas1_prep0 | 73 | 0.6622 | undefined: non_positive_minimum | 0.6065 |
| qubit/143 | prob_meas1_prep0 | 73 | 0.9276 | 92 | 0.938 |
| qubit/144 | prob_meas1_prep0 | 73 | 1.653 | undefined: non_positive_minimum | 1.289 |
| qubit/136 | init_error | 16 | 1.08 | 50.84 | 1.029 |
| qubit/141 | init_error | 15 | 1.705 | 132.3 | 1.775 |
| qubit/142 | init_error | 16 | 0.5572 | 12.15 | 0.4947 |
| qubit/143 | init_error | 16 | 0.6076 | 12.03 | 0.5706 |
| qubit/144 | init_error | 16 | 0.7251 | 4.786e+06 | 0.6622 |
| gate/sx/136 | gate_error | 73 | 0.1685 | 2.399 | 0.1697 |
| gate/sx/141 | gate_error | 73 | 0.6497 | 12.39 | 0.5071 |
| gate/sx/142 | gate_error | 73 | 0.3468 | 6.824 | 0.3144 |
| gate/sx/143 | gate_error | 73 | 0.2253 | 2.593 | 0.232 |
| gate/sx/144 | gate_error | 73 | 0.4524 | 9.659 | 0.4508 |
| gate/measure/136 | gate_error | 73 | 0.4075 | 6.192 | 0.3357 |
| gate/measure/141 | gate_error | 73 | 0.5636 | 10.67 | 0.5274 |
| gate/measure/142 | gate_error | 73 | 0.6777 | 11.54 | 0.6915 |
| gate/measure/143 | gate_error | 73 | 0.575 | 10.55 | 0.5395 |
| gate/measure/144 | gate_error | 73 | 0.9559 | 27.88 | 0.7634 |
| gate/cz/142,141 | gate_error | 73 | 0.3107 | 4.047 | 0.294 |
| gate/cz/142,143 | gate_error | 73 | 0.661 | 9.116 | 0.6083 |
| gate/cz/143,136 | gate_error | 73 | 1.516 | 30.54 | 1.36 |
| gate/cz/143,142 | gate_error | 73 | 0.661 | 9.116 | 0.6083 |
| gate/cz/143,144 | gate_error | 73 | 0.4053 | 4.674 | 0.267 |

### Sparse: lag profile (Kendall's tau-b, G_0 against G_k)

| Parameter | G_1 | G_2 | G_6 | G_12 | G_18 | G_36 | G_72 |
|---|---|---|---|---|---|---|---|
| readout_error | 0.8 (n=5, same doc: no, same date: 0) | 0.4 (n=5, same doc: no, same date: 0) | 0.7379 (n=5, same doc: no, same date: 0) | 0.2 (n=5, same doc: no, same date: 0) | -0.2 (n=5, same doc: no, same date: 0) | 0.2 (n=5, same doc: no, same date: 0) | 0.4 (n=5, same doc: no, same date: 0) |
| T1 | 0.6 (n=5, same doc: no, same date: 0) | 0.4 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) | -0.4 (n=5, same doc: no, same date: 0) | 0 (n=5, same doc: no, same date: 0) | 0.2 (n=5, same doc: no, same date: 0) |
| cz gate_error | -0.3333 (n=5, same doc: no, same date: 0) | 0.7778 (n=5, same doc: no, same date: 0) | -0.1111 (n=5, same doc: no, same date: 0) | -0.3333 (n=5, same doc: no, same date: 0) | -0.1111 (n=5, same doc: no, same date: 0) | -0.3333 (n=5, same doc: no, same date: 0) | -0.7778 (n=5, same doc: no, same date: 0) |

## ibm_kingston

### Sets

| Set | grid_times | lookups_present | missing_grid_times | distinct_documents | documents_without_stamp | stamp_ties | documents_with_unusable_in_scope_series | requested - stamp, median h | max h |
|---|---|---|---|---|---|---|---|---|---|
| dense | 169 | 169 | 0 | 157 | 0 | 0 | 0 | 0.4972 | 2.07 |
| sparse | 73 | 73 | 0 | 71 | 0 | 0 | 55 | 0.885 | 166.8 |

| Set | missing_row | duplicate_rows | null_value | non_numeric_value | non_finite_value | missing_date |
|---|---|---|---|---|---|---|
| dense | 0 | 0 | 0 | 0 | 0 | 0 |
| sparse | 275 | 0 | 0 | 0 | 0 | 0 |

### Dense: per-parameter medians over footprint resources

| Parameter | resources | median CV | (defined) | median max/min | (defined) | median d/m | (defined) |
|---|---|---|---|---|---|---|---|
| T1 | 5 | 0.2199 | 5 | 1.762 | 5 | 0.1841 | 5 |
| T2 | 5 | 0.2028 | 5 | 1.725 | 5 | 0.1632 | 5 |
| readout_error | 5 | 0.4674 | 5 | 6.6 | 5 | 0.4357 | 5 |
| prob_meas0_prep1 | 5 | 0.5831 | 5 | 7.455 | 5 | 0.5725 | 5 |
| prob_meas1_prep0 | 5 | 0.6336 | 5 | 9.5 | 3 | 0.547 | 5 |
| init_error | 5 | 0.7577 | 5 | 30.29 | 5 | 0.7078 | 5 |
| sx gate_error | 5 | 0.2554 | 5 | 2.081 | 5 | 0.2219 | 5 |
| measure gate_error | 5 | 0.4674 | 5 | 6.6 | 5 | 0.4357 | 5 |
| cz gate_error | 5 | 0.2646 | 5 | 2.427 | 5 | 0.2758 | 5 |

### Dense: per series

| Resource | Parameter | n | unavailable | not_re_measured | revised_same_date | re_measured_same_value | re_measured_different_value | date_earlier | interval median h | CV | max/min | d/m |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qubit/138 | T1 | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.97 | 0.1723 | 1.685 | 0.1841 |
| qubit/149 | T1 | 7 | 0 | 150 | 0 | 0 | 6 | 0 | 24.74 | 0.2339 | 1.823 | 0.2196 |
| qubit/150 | T1 | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.97 | 0.1203 | 1.422 | 0.13 |
| qubit/151 | T1 | 7 | 0 | 150 | 0 | 0 | 6 | 0 | 25.77 | 0.22 | 2.214 | 0.1859 |
| qubit/152 | T1 | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.97 | 0.2199 | 1.762 | 0.1436 |
| qubit/138 | T2 | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.97 | 0.2258 | 1.725 | 0.2276 |
| qubit/149 | T2 | 7 | 0 | 150 | 0 | 0 | 6 | 0 | 24.73 | 0.2359 | 2.08 | 0.1996 |
| qubit/150 | T2 | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.97 | 0.1405 | 1.572 | 0.1632 |
| qubit/151 | T2 | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.97 | 0.2028 | 1.829 | 0.1553 |
| qubit/152 | T2 | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.97 | 0.1079 | 1.453 | 0.1091 |
| qubit/138 | readout_error | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.357 | 1.835 | 46.55 | 1.818 |
| qubit/149 | readout_error | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.357 | 0.419 | 6.583 | 0.4357 |
| qubit/150 | readout_error | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.357 | 0.4674 | 6.6 | 0.4187 |
| qubit/151 | readout_error | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.357 | 0.5126 | 8.364 | 0.5308 |
| qubit/152 | readout_error | 36 | 0 | 121 | 0 | 1 | 34 | 0 | 4.357 | 0.2544 | 3.061 | 0.2596 |
| qubit/138 | prob_meas0_prep1 | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.354 | 2.356 | 73.26 | 2.389 |
| qubit/149 | prob_meas0_prep1 | 36 | 0 | 121 | 0 | 1 | 34 | 0 | 4.354 | 0.4131 | 5 | 0.3706 |
| qubit/150 | prob_meas0_prep1 | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.354 | 0.5831 | 7.455 | 0.5725 |
| qubit/151 | prob_meas0_prep1 | 36 | 0 | 121 | 0 | 1 | 34 | 0 | 4.354 | 0.6856 | 11.73 | 0.7016 |
| qubit/152 | prob_meas0_prep1 | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.52 | 0.3788 | 2.692 | 0.4042 |
| qubit/138 | prob_meas1_prep0 | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.355 | 2.042 | undefined: non_positive_minimum | 1.921 |
| qubit/149 | prob_meas1_prep0 | 36 | 0 | 121 | 0 | 2 | 33 | 0 | 4.355 | 0.8542 | undefined: non_positive_minimum | 0.8339 |
| qubit/150 | prob_meas1_prep0 | 36 | 0 | 121 | 0 | 1 | 34 | 0 | 4.355 | 0.4997 | 13.75 | 0.441 |
| qubit/151 | prob_meas1_prep0 | 36 | 0 | 121 | 0 | 4 | 31 | 0 | 4.355 | 0.6336 | 9.5 | 0.547 |
| qubit/152 | prob_meas1_prep0 | 36 | 0 | 121 | 0 | 3 | 32 | 0 | 4.355 | 0.428 | 6 | 0.4352 |
| qubit/138 | init_error | 44 | 0 | 113 | 0 | 0 | 43 | 0 | 3.081 | 1.222 | 116.6 | 1.274 |
| qubit/149 | init_error | 46 | 0 | 111 | 0 | 1 | 44 | 0 | 3.064 | 0.7577 | 17.03 | 0.7078 |
| qubit/150 | init_error | 46 | 0 | 111 | 0 | 0 | 45 | 0 | 3.064 | 0.8027 | 32.97 | 0.8443 |
| qubit/151 | init_error | 46 | 0 | 111 | 0 | 0 | 45 | 0 | 3.064 | 0.6711 | 30.29 | 0.5673 |
| qubit/152 | init_error | 30 | 0 | 127 | 0 | 0 | 29 | 0 | 4.888 | 0.4064 | 9.677 | 0.4389 |
| gate/sx/138 | gate_error | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.73 | 0.2554 | 1.988 | 0.2219 |
| gate/sx/149 | gate_error | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.73 | 0.1844 | 2.058 | 0.1823 |
| gate/sx/150 | gate_error | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.73 | 0.2197 | 2.081 | 0.2942 |
| gate/sx/151 | gate_error | 7 | 0 | 150 | 0 | 0 | 6 | 0 | 24.75 | 0.875 | 6.597 | 0.9503 |
| gate/sx/152 | gate_error | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.73 | 0.2882 | 2.131 | 0.2058 |
| gate/measure/138 | gate_error | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.357 | 1.835 | 46.55 | 1.818 |
| gate/measure/149 | gate_error | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.357 | 0.419 | 6.583 | 0.4357 |
| gate/measure/150 | gate_error | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.357 | 0.4674 | 6.6 | 0.4187 |
| gate/measure/151 | gate_error | 36 | 0 | 121 | 0 | 0 | 35 | 0 | 4.357 | 0.5126 | 8.364 | 0.5308 |
| gate/measure/152 | gate_error | 36 | 0 | 121 | 0 | 1 | 34 | 0 | 4.357 | 0.2544 | 3.061 | 0.2596 |
| gate/cz/150,149 | gate_error | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.95 | 0.206 | 1.728 | 0.2108 |
| gate/cz/150,151 | gate_error | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.95 | 0.2646 | 2.427 | 0.2758 |
| gate/cz/151,138 | gate_error | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.95 | 0.2027 | 1.717 | 0.2337 |
| gate/cz/151,150 | gate_error | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.95 | 0.2646 | 2.427 | 0.2758 |
| gate/cz/151,152 | gate_error | 8 | 0 | 149 | 0 | 0 | 7 | 0 | 24.95 | 1.184 | 9.396 | 1.226 |

### Sparse: per series

| Resource | Parameter | n | CV | max/min | d/m |
|---|---|---|---|---|---|
| qubit/138 | T1 | 70 | 0.2208 | 2.97 | 0.2001 |
| qubit/149 | T1 | 69 | 0.2678 | 5.563 | 0.2482 |
| qubit/150 | T1 | 70 | 0.2257 | 2.76 | 0.1984 |
| qubit/151 | T1 | 71 | 0.2139 | 2.419 | 0.1889 |
| qubit/152 | T1 | 70 | 0.235 | 2.992 | 0.243 |
| qubit/138 | T2 | 71 | 0.2253 | 2.958 | 0.1932 |
| qubit/149 | T2 | 70 | 0.3253 | 5.623 | 0.252 |
| qubit/150 | T2 | 70 | 0.266 | 4.144 | 0.2347 |
| qubit/151 | T2 | 71 | 0.1894 | 6.64 | 0.1716 |
| qubit/152 | T2 | 71 | 0.2586 | 3.113 | 0.1758 |
| qubit/138 | readout_error | 71 | 3.709 | 113.2 | 3.742 |
| qubit/149 | readout_error | 71 | 4.662 | 1027 | 4.703 |
| qubit/150 | readout_error | 71 | 3.057 | 98.55 | 3.034 |
| qubit/151 | readout_error | 71 | 4.291 | 241.1 | 4.323 |
| qubit/152 | readout_error | 71 | 4.126 | 147.9 | 4.155 |
| qubit/138 | prob_meas0_prep1 | 71 | 2.999 | 95.9 | 3.037 |
| qubit/149 | prob_meas0_prep1 | 71 | 2.919 | 316.2 | 2.949 |
| qubit/150 | prob_meas0_prep1 | 71 | 2.976 | 96.2 | 2.997 |
| qubit/151 | prob_meas0_prep1 | 71 | 3.028 | 126 | 3.072 |
| qubit/152 | prob_meas0_prep1 | 71 | 3.298 | 145.8 | 3.335 |
| qubit/138 | prob_meas1_prep0 | 71 | 4.769 | 2156 | 4.794 |
| qubit/149 | prob_meas1_prep0 | 71 | 6.471 | undefined: non_positive_minimum | 6.52 |
| qubit/150 | prob_meas1_prep0 | 71 | 3.138 | 184.6 | 3.071 |
| qubit/151 | prob_meas1_prep0 | 71 | 5.302 | 1420 | 5.329 |
| qubit/152 | prob_meas1_prep0 | 71 | 5.191 | 597.8 | 5.209 |
| qubit/138 | init_error | 16 | 1.112 | 58.77 | 1.002 |
| qubit/149 | init_error | 16 | 0.8191 | 17.97 | 0.8267 |
| qubit/150 | init_error | 15 | 0.3297 | 4.429 | 0.2942 |
| qubit/151 | init_error | 16 | 0.7036 | 31.84 | 0.6957 |
| qubit/152 | init_error | 16 | 0.5953 | 11.91 | 0.5382 |
| gate/sx/138 | gate_error | 69 | 0.5757 | 9.113 | 0.5659 |
| gate/sx/149 | gate_error | 69 | 0.5652 | 8.03 | 0.5183 |
| gate/sx/150 | gate_error | 69 | 0.2922 | 4.844 | 0.2963 |
| gate/sx/151 | gate_error | 69 | 0.9763 | 14.63 | 0.8244 |
| gate/sx/152 | gate_error | 68 | 1.894 | 44.77 | 1.932 |
| gate/measure/138 | gate_error | 71 | 3.709 | 113.2 | 3.742 |
| gate/measure/149 | gate_error | 71 | 4.662 | 1027 | 4.703 |
| gate/measure/150 | gate_error | 71 | 3.057 | 98.55 | 3.034 |
| gate/measure/151 | gate_error | 71 | 4.291 | 241.1 | 4.323 |
| gate/measure/152 | gate_error | 71 | 4.126 | 147.9 | 4.155 |
| gate/cz/150,149 | gate_error | 71 | 0.3426 | 5.247 | 0.2807 |
| gate/cz/150,151 | gate_error | 69 | 0.3226 | 3.754 | 0.2782 |
| gate/cz/151,138 | gate_error | 69 | 0.9578 | 16.48 | 0.8729 |
| gate/cz/151,150 | gate_error | 69 | 0.3226 | 3.754 | 0.2782 |
| gate/cz/151,152 | gate_error | 70 | 0.9105 | 10.37 | 0.9353 |

### Sparse: lag profile (Kendall's tau-b, G_0 against G_k)

| Parameter | G_1 | G_2 | G_6 | G_12 | G_18 | G_36 | G_72 |
|---|---|---|---|---|---|---|---|
| readout_error | 0.4 (n=5, same doc: no, same date: 0) | 0.8 (n=5, same doc: no, same date: 0) | 0.4 (n=5, same doc: no, same date: 0) | 0.8 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) | 0.3162 (n=5, same doc: no, same date: 0) | 0.2 (n=5, same doc: no, same date: 0) |
| T1 | -0.4 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) | 0.4 (n=5, same doc: no, same date: 0) | 0.8 (n=5, same doc: no, same date: 0) | -0.4 (n=5, same doc: no, same date: 0) | 0.4 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) |
| cz gate_error | 0.1111 (n=5, same doc: no, same date: 0) | 1 (n=5, same doc: no, same date: 0) | 1 (n=5, same doc: no, same date: 0) | 0.7778 (n=5, same doc: no, same date: 0) | 0.5556 (n=5, same doc: no, same date: 0) | 0.3333 (n=5, same doc: no, same date: 0) | 0.3333 (n=5, same doc: no, same date: 0) |

## ibm_marrakesh

### Sets

| Set | grid_times | lookups_present | missing_grid_times | distinct_documents | documents_without_stamp | stamp_ties | documents_with_unusable_in_scope_series | requested - stamp, median h | max h |
|---|---|---|---|---|---|---|---|---|---|
| dense | 169 | 169 | 0 | 151 | 0 | 0 | 0 | 0.4003 | 2.423 |
| sparse | 73 | 73 | 0 | 73 | 0 | 0 | 57 | 0.6689 | 68.67 |

| Set | missing_row | duplicate_rows | null_value | non_numeric_value | non_finite_value | missing_date |
|---|---|---|---|---|---|---|
| dense | 0 | 0 | 0 | 0 | 0 | 0 |
| sparse | 285 | 0 | 0 | 0 | 0 | 0 |

### Dense: per-parameter medians over footprint resources

| Parameter | resources | median CV | (defined) | median max/min | (defined) | median d/m | (defined) |
|---|---|---|---|---|---|---|---|
| T1 | 5 | 0.2697 | 5 | 2.376 | 5 | 0.2819 | 5 |
| T2 | 5 | 0.1736 | 5 | 1.609 | 5 | 0.1391 | 5 |
| readout_error | 5 | 1.232 | 5 | 36.8 | 5 | 1.122 | 5 |
| prob_meas0_prep1 | 5 | 0.923 | 5 | 11.73 | 5 | 0.7532 | 5 |
| prob_meas1_prep0 | 5 | 1.936 | 5 | 319 | 3 | 1.716 | 5 |
| init_error | 5 | 1.014 | 4 | 112.6 | 4 | 0.8063 | 4 |
| sx gate_error | 5 | 0.2771 | 5 | 2.178 | 5 | 0.2875 | 5 |
| measure gate_error | 5 | 1.232 | 5 | 36.8 | 5 | 1.122 | 5 |
| cz gate_error | 5 | 1.989 | 5 | 28.11 | 5 | 1.527 | 5 |

### Dense: per series

| Resource | Parameter | n | unavailable | not_re_measured | revised_same_date | re_measured_same_value | re_measured_different_value | date_earlier | interval median h | CV | max/min | d/m |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qubit/10 | T1 | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.88 | 0.2514 | 2.376 | 0.2749 |
| qubit/11 | T1 | 7 | 0 | 144 | 0 | 0 | 6 | 0 | 24.97 | 0.2697 | 2.498 | 0.2819 |
| qubit/12 | T1 | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.88 | 0.3413 | 2.313 | 0.3059 |
| qubit/13 | T1 | 7 | 0 | 144 | 0 | 0 | 6 | 0 | 24.91 | 0.1348 | 1.579 | 0.1133 |
| qubit/18 | T1 | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.88 | 0.4336 | 10.16 | 0.4873 |
| qubit/10 | T2 | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.88 | 0.2427 | 1.908 | 0.198 |
| qubit/11 | T2 | 7 | 0 | 144 | 0 | 0 | 6 | 0 | 24.97 | 0.1619 | 1.501 | 0.1391 |
| qubit/12 | T2 | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.88 | 0.1736 | 1.609 | 0.1125 |
| qubit/13 | T2 | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.88 | 0.06718 | 1.248 | 0.06219 |
| qubit/18 | T2 | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.88 | 0.4024 | 7.877 | 0.4802 |
| qubit/10 | readout_error | 59 | 0 | 92 | 0 | 1 | 57 | 0 | 1.413 | 1.232 | 47.3 | 1.122 |
| qubit/11 | readout_error | 59 | 0 | 92 | 0 | 0 | 58 | 0 | 1.413 | 1.601 | 46.55 | 1.373 |
| qubit/12 | readout_error | 59 | 0 | 92 | 0 | 1 | 57 | 0 | 1.413 | 1.164 | 28.24 | 1.117 |
| qubit/13 | readout_error | 59 | 0 | 92 | 0 | 0 | 58 | 0 | 1.413 | 1.736 | 36.8 | 1.278 |
| qubit/18 | readout_error | 59 | 0 | 92 | 0 | 0 | 58 | 0 | 1.413 | 0.8381 | 27.25 | 0.815 |
| qubit/10 | prob_meas0_prep1 | 59 | 0 | 92 | 0 | 2 | 56 | 0 | 1.413 | 0.9499 | 30.8 | 0.809 |
| qubit/11 | prob_meas0_prep1 | 59 | 0 | 92 | 0 | 0 | 58 | 0 | 1.413 | 1.338 | 34.85 | 1.202 |
| qubit/12 | prob_meas0_prep1 | 59 | 0 | 92 | 0 | 3 | 55 | 0 | 1.413 | 0.6386 | 11.73 | 0.6322 |
| qubit/13 | prob_meas0_prep1 | 59 | 0 | 92 | 0 | 1 | 57 | 0 | 1.413 | 0.923 | 11.17 | 0.7532 |
| qubit/18 | prob_meas0_prep1 | 59 | 0 | 92 | 0 | 1 | 57 | 0 | 1.413 | 0.5341 | 10.09 | 0.5366 |
| qubit/10 | prob_meas1_prep0 | 59 | 0 | 92 | 0 | 0 | 58 | 0 | 1.413 | 1.55 | 319 | 1.447 |
| qubit/11 | prob_meas1_prep0 | 59 | 0 | 92 | 0 | 1 | 57 | 0 | 1.413 | 2.427 | 1966 | 2.129 |
| qubit/12 | prob_meas1_prep0 | 59 | 0 | 92 | 0 | 3 | 55 | 0 | 1.413 | 1.936 | undefined: non_positive_minimum | 1.825 |
| qubit/13 | prob_meas1_prep0 | 59 | 0 | 92 | 0 | 2 | 56 | 0 | 1.413 | 2.356 | 137 | 1.716 |
| qubit/18 | prob_meas1_prep0 | 59 | 0 | 92 | 0 | 1 | 57 | 0 | 1.413 | 1.241 | undefined: non_positive_minimum | 1.193 |
| qubit/10 | init_error | 62 | 0 | 89 | 0 | 0 | 61 | 0 | 1.356 | 0.9012 | 160 | 0.7379 |
| qubit/11 | init_error | 6 | 0 | 145 | 0 | 0 | 5 | 0 | 25.97 | 1.555 | 51.33 | 1.145 |
| qubit/12 | init_error | 62 | 0 | 89 | 0 | 0 | 61 | 0 | 1.298 | 1.127 | 105.2 | 0.7052 |
| qubit/13 | init_error | 1 | 0 | 150 | 0 | 0 | 0 | 0 | - | undefined: too_few_measurements | undefined: too_few_measurements | undefined: too_few_measurements |
| qubit/18 | init_error | 58 | 0 | 93 | 0 | 0 | 57 | 0 | 1.368 | 0.8998 | 120 | 0.8748 |
| gate/sx/10 | gate_error | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.89 | 0.4738 | 3.535 | 0.4229 |
| gate/sx/11 | gate_error | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.89 | 0.1363 | 1.484 | 0.1416 |
| gate/sx/12 | gate_error | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.89 | 0.4137 | 3.554 | 0.4322 |
| gate/sx/13 | gate_error | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.89 | 0.2771 | 2.141 | 0.2238 |
| gate/sx/18 | gate_error | 7 | 0 | 144 | 0 | 0 | 6 | 0 | 25.09 | 0.2455 | 2.178 | 0.2875 |
| gate/measure/10 | gate_error | 59 | 0 | 92 | 0 | 1 | 57 | 0 | 1.413 | 1.232 | 47.3 | 1.122 |
| gate/measure/11 | gate_error | 59 | 0 | 92 | 0 | 0 | 58 | 0 | 1.413 | 1.601 | 46.55 | 1.373 |
| gate/measure/12 | gate_error | 59 | 0 | 92 | 0 | 1 | 57 | 0 | 1.413 | 1.164 | 28.24 | 1.117 |
| gate/measure/13 | gate_error | 59 | 0 | 92 | 0 | 0 | 58 | 0 | 1.413 | 1.736 | 36.8 | 1.278 |
| gate/measure/18 | gate_error | 59 | 0 | 92 | 0 | 0 | 58 | 0 | 1.413 | 0.8381 | 27.25 | 0.815 |
| gate/cz/11,10 | gate_error | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.96 | 2.215 | 34.83 | 1.683 |
| gate/cz/11,12 | gate_error | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.96 | 1.989 | 28.11 | 1.527 |
| gate/cz/11,18 | gate_error | 7 | 0 | 144 | 0 | 0 | 6 | 0 | 25.13 | 1.938 | 26.76 | 1.478 |
| gate/cz/12,11 | gate_error | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.96 | 1.989 | 28.11 | 1.527 |
| gate/cz/12,13 | gate_error | 8 | 0 | 143 | 0 | 0 | 7 | 0 | 24.96 | 1.401 | 11.93 | 1.463 |

### Sparse: per series

| Resource | Parameter | n | CV | max/min | d/m |
|---|---|---|---|---|---|
| qubit/10 | T1 | 73 | 0.2399 | 4.2 | 0.1957 |
| qubit/11 | T1 | 73 | 0.254 | 4.138 | 0.1998 |
| qubit/12 | T1 | 73 | 0.2261 | 5.02 | 0.2196 |
| qubit/13 | T1 | 73 | 0.2266 | 8.198 | 0.2099 |
| qubit/18 | T1 | 73 | 0.2018 | 3.644 | 0.1757 |
| qubit/10 | T2 | 73 | 0.3115 | 5.607 | 0.2371 |
| qubit/11 | T2 | 73 | 0.2899 | 5.709 | 0.2749 |
| qubit/12 | T2 | 73 | 0.2477 | 6.307 | 0.2227 |
| qubit/13 | T2 | 73 | 0.2766 | 9.453 | 0.2669 |
| qubit/18 | T2 | 73 | 0.3943 | 8.731 | 0.3412 |
| qubit/10 | readout_error | 73 | 4.205 | 256 | 4.258 |
| qubit/11 | readout_error | 73 | 2.459 | 81.62 | 2.534 |
| qubit/12 | readout_error | 73 | 4.413 | 288.3 | 4.432 |
| qubit/13 | readout_error | 73 | 1.775 | 162.2 | 1.617 |
| qubit/18 | readout_error | 73 | 2.248 | 89.56 | 2.276 |
| qubit/10 | prob_meas0_prep1 | 73 | 0.509 | 11.4 | 0.4159 |
| qubit/11 | prob_meas0_prep1 | 73 | 0.964 | 17.7 | 1.002 |
| qubit/12 | prob_meas0_prep1 | 73 | 0.5423 | 19 | 0.5372 |
| qubit/13 | prob_meas0_prep1 | 73 | 2.956 | 202.8 | 2.916 |
| qubit/18 | prob_meas0_prep1 | 73 | 0.7008 | 13.37 | 0.7068 |
| qubit/10 | prob_meas1_prep0 | 73 | 6.432 | undefined: non_positive_minimum | 6.498 |
| qubit/11 | prob_meas1_prep0 | 73 | 3.646 | 1870 | 3.718 |
| qubit/12 | prob_meas1_prep0 | 73 | 6.935 | undefined: non_positive_minimum | 6.987 |
| qubit/13 | prob_meas1_prep0 | 73 | 1.403 | undefined: non_positive_minimum | 1.219 |
| qubit/18 | prob_meas1_prep0 | 73 | 4.215 | 1680 | 4.251 |
| qubit/10 | init_error | 16 | 0.6457 | 12.29 | 0.6963 |
| qubit/11 | init_error | 14 | 1.633 | 3852 | 1.521 |
| qubit/12 | init_error | 16 | 0.8718 | 15.87 | 0.7475 |
| qubit/13 | init_error | 8 | 0.8658 | 25.74 | 0.6129 |
| qubit/18 | init_error | 16 | 1.547 | 9.624e+48 | 1.247 |
| gate/sx/10 | gate_error | 73 | 0.2778 | 3.95 | 0.2912 |
| gate/sx/11 | gate_error | 73 | 0.365 | 5.432 | 0.3584 |
| gate/sx/12 | gate_error | 73 | 0.4073 | 5.548 | 0.3953 |
| gate/sx/13 | gate_error | 73 | 0.7935 | 13.14 | 0.7716 |
| gate/sx/18 | gate_error | 73 | 0.6297 | 10.6 | 0.5681 |
| gate/measure/10 | gate_error | 73 | 4.205 | 256 | 4.258 |
| gate/measure/11 | gate_error | 73 | 2.459 | 81.62 | 2.534 |
| gate/measure/12 | gate_error | 73 | 4.413 | 288.3 | 4.432 |
| gate/measure/13 | gate_error | 73 | 1.775 | 162.2 | 1.617 |
| gate/measure/18 | gate_error | 73 | 2.248 | 89.56 | 2.276 |
| gate/cz/11,10 | gate_error | 73 | 0.3693 | 4.702 | 0.3792 |
| gate/cz/11,12 | gate_error | 73 | 0.3067 | 4.463 | 0.2944 |
| gate/cz/11,18 | gate_error | 73 | 0.5085 | 7.233 | 0.5113 |
| gate/cz/12,11 | gate_error | 73 | 0.3067 | 4.463 | 0.2944 |
| gate/cz/12,13 | gate_error | 73 | 0.5417 | 7.144 | 0.5625 |

### Sparse: lag profile (Kendall's tau-b, G_0 against G_k)

| Parameter | G_1 | G_2 | G_6 | G_12 | G_18 | G_36 | G_72 |
|---|---|---|---|---|---|---|---|
| readout_error | 0 (n=5, same doc: no, same date: 0) | 0.8 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) | 0.3162 (n=5, same doc: no, same date: 0) | 0.2 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) |
| T1 | 0.6 (n=5, same doc: no, same date: 0) | 0.8 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) | 1 (n=5, same doc: no, same date: 0) | 0.8 (n=5, same doc: no, same date: 0) | 0.2 (n=5, same doc: no, same date: 0) | 0.6 (n=5, same doc: no, same date: 0) |
| cz gate_error | 0.1111 (n=5, same doc: no, same date: 0) | 1 (n=5, same doc: no, same date: 0) | -0.3333 (n=5, same doc: no, same date: 0) | 0.7778 (n=5, same doc: no, same date: 0) | 0.7778 (n=5, same doc: no, same date: 0) | 0.7778 (n=5, same doc: no, same date: 0) | 0.5556 (n=5, same doc: no, same date: 0) |

