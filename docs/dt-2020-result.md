# C2S7N02020 D+T result

The single authorized cold run of `C2S7N02020/scenario_001` used frozen commit `923def7` and
configuration `configs/GOC2-DC-D1-CORRECTIVE-v2-2020-dt.json` (SHA-256
`5c0709d7375048e3f0e5f1cbee49d9947e6d7ac69a37729c578bde5894a9a17f`). It began at
2026-08-21T02:40:02Z and completed successfully without a retry. The registered end-to-end limit
was 1,800 seconds.

## Acceptance result

| Gate | Result |
|---|---:|
| Official status | success |
| Primary model status | Optimal |
| Primary objective | -2,599,592.663551945 USD |
| Primary dual bound | -2,599,592.663551945 USD |
| Certified relative gap | 0.0 |
| Fixed-commitment pricing LP | Optimal |
| Recomputed pricing objective | -2,599,592.663551939 USD |
| Source contingencies checked | 328 of 328 |
| States checked | 329 of 329 |
| Maximum model residual | 2.342e-9 p.u. |
| Maximum exhaustive security violation | 1.466e-9 p.u. |
| Checker status | pass |

The objective uses the registered minimization convention of generation and commitment cost minus
source-authorized load benefit. It is not an official GO score, and its magnitude should not be
compared directly with a different network's objective.

## Base decision and prices

| Quantity | Result |
|---|---:|
| Source generators | 194 |
| Prior-online generators | 194 |
| Base committed generators | 186 |
| Base-off generators | 8 |
| Base generation | 13,552.637241 MW |
| Base served load | 13,552.637241 MW |
| Contingency fast starts | 0 |
| Nodal prices reported | 2,020 |
| Minimum price | 10.782000 USD/MWh |
| Mean price | 23.031008 USD/MWh |
| Maximum price | 27.270829 USD/MWh |

The eight base-off source generators are `(bus, id)` = `(1757, 1)`, `(1758, 1)`, `(1898, 1)`,
`(1899, 1)`, `(1900, 1)`, `(1901, 1)`, `(1922, 1)`, and `(2014, 1)`. The full ordered base and
contingency commitments and dispatches and all 2,020 prices remain in the hashed local result
artifacts; this repository intentionally ignores raw results.

## Timing and algorithm attribution

| Stage | Seconds |
|---|---:|
| Source ingest | 2.844 |
| Complete canonical model build | 6.722 |
| D+T primary total | 113.457 |
| Restricted base master solve | 0.339 |
| Exhaustive contingency screens | 97.084 |
| Primary checkpoint serialization | 0.314 |
| Independent primary verification | 5.489 |
| Fixed-commitment pricing LP | 886.303 |
| Initial result serialization | 0.964 |
| Final independent verification | 8.675 |
| End to end | 1,024.785 |

D+T completed in one scenario-generation round. Its base-only restricted master was already
correctively feasible for all 328 source contingencies, so it added no contingency blocks and did
not re-solve the master. The pricing LP, not the primary MILP or contingency screening, dominated
runtime: it used 751,193 simplex iterations and about 86.5% of end-to-end time. Peak resident memory
was 4,216,483,840 bytes (3.93 GiB).

For context, the previously accepted 617-bus D+T cell completed in 288.530 seconds with a 0.0449%
gap. The 2,020-bus run took 1,024.785 seconds and closed its bound exactly. Both completed in one
round and passed their full source contingency sets; this is a case-to-case comparison, not a pure
bus-count scaling law, because the 617-bus case has 815 contingencies while this case has 328.

## Local artifact identity

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `result.json` | 11,608,262 | `26c9229ebb11984ed9c2f1a85cbe33f633c0adb301a586f2e7b0ce64d1ff76d0` |
| `primary-checkpoint.json` | 4,926 | `271c344dc3bd67a93a9a7fbdea45ce5d8fa7798d947da8f9f941a1df032512f1` |
| `primary-primal.npz` | 9,276,600 | `a26b0dfdb689b765d4a0444d07628082b0aa4b8387e4587b2ac570f834d41d13` |
| `pricing-primal.npz` | 9,889,125 | `379bdfd26043e85a88ad8297d9927baccb282f50d9edef3a6c91b5dbbe2d538b` |

These artifacts are local at `C:\Users\thoma\Documents\goc2-dc-scopf-cpu\results\default-2020-dt`.
They were not copied to OneDrive and are excluded from Git by the repository contract.
