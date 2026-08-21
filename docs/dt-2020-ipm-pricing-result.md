# C2S7N02020 D+T presolved-IPM pricing result

The single authorized cold run of `C2S7N02020/scenario_001` used frozen commit
`99ccb1bdb08d92408602d8913f6a04934c41514d` and configuration
`configs/GOC2-DC-D1-CORRECTIVE-v2-2020-dt-ipm-pricing.json` (SHA-256
`fbb75058c8dd4f239d70e0f39934c716d3290630782531a3494e37041ba4b6c1`). It began at
2026-08-21T17:45:20Z and completed successfully at 2026-08-21T18:06:27Z without a retry. The
registered end-to-end limit was 1,800 seconds.

The D+T primary algorithm, model, source case, tolerances, 0.1% MIP-gap target, and exhaustive
security checker were unchanged. The experiment changed only fixed-commitment pricing from a
fresh presolved simplex solve to a fresh presolved interior-point solve. It supplied neither a
basis nor a primal start, and left crossover enabled so that HiGHS could return checked row duals
for prices.

## Result

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
| Price-dual consistency error | 0.0 USD/MWh |
| Checker status | pass |

The objective uses the registered minimization convention of generation and commitment cost minus
source-authorized load benefit. It is not an official GO score.

## What the requested IPM route actually did

Presolve reduced the pricing LP from 3,095,343 rows, 2,322,377 columns, and 8,519,921 nonzeros to
698,039 rows, 1,104,528 columns, and 3,638,767 nonzeros. HiGHS 1.15.1 then selected HiPO for the
requested `solver=ipm` path.

HiPO performed 61 iterations but stopped with `no progress` before producing a sufficiently
accurate primal solution. HiGHS passed that iterate to IPX, which performed another 5 interior-point
iterations and also reported no progress. Because crossover was enabled and the basis was invalid,
HiGHS automatically used parallel dual simplex to clean up the solution. That cleanup required
751,193 simplex iterations and obtained an optimal, primal-feasible basis.

Thus this was a valid IPM-requested experiment, but it did not finish as a pure interior-point
solve: the successful price result depended on simplex cleanup.

## Timing comparison

| Case and pricing method | Primary total (s) | Pricing (s) | End to end (s) | Pricing iterations | Primary objective (USD) | Bound (USD) | Gap | Check |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 617 D+T, fresh presolved simplex | 56.041 | 213.293 | 288.530 | 528,058 simplex | -227,041.741687 | -227,143.685516 | 0.000449 | pass |
| 2,020 D+T, fresh presolved simplex | 113.457 | 886.303 | 1,024.785 | 751,193 simplex | -2,599,592.663552 | -2,599,592.663552 | 0.0 | pass |
| 2,020 D+T, fresh presolved IPM | 113.197 | 1,129.297 | 1,267.290 | 66 IPM + 751,193 simplex | -2,599,592.663552 | -2,599,592.663552 | 0.0 | pass |

The 617-bus row is scale context, not an algorithm comparison: it is a different case with 815
source contingencies. The controlled 2,020-bus comparison shows that IPM increased pricing time by
242.994 seconds (27.4%) and end-to-end time by 242.505 seconds (23.7%). Peak resident memory was
4,133,269,504 bytes (3.85 GiB), versus 4,216,483,840 bytes (3.93 GiB) in the saved 2,020-bus
simplex run.

## Decision, dispatch, and price identity

| Quantity | IPM experiment | Difference from 2,020 simplex baseline |
|---|---:|---:|
| Committed generators | 186 of 194 | 0 units |
| Base generation | 13,552.637241 MW | 0.0 MW maximum per generator |
| Base served load | 13,552.637241 MW | 0.0 MW total |
| Prices reported | 2,020 | 0 buses |
| Minimum price | 10.782000 USD/MWh | 0.0 USD/MWh |
| Mean price | 23.031008 USD/MWh | 0.0 USD/MWh |
| Maximum price | 27.270829 USD/MWh | 0.0 USD/MWh |

The complete primary and pricing primal artifacts are byte-identical to the saved 2,020-bus
simplex baseline. Therefore the longer time was solver-path overhead, not a different commitment,
dispatch, price vector, or economic solution.

## Detailed timing

| Stage | Seconds |
|---|---:|
| Source ingest | 2.811 |
| Complete canonical model build | 6.686 |
| D+T primary total | 113.197 |
| Primary checkpoint serialization | 0.317 |
| Independent primary verification | 5.429 |
| Fixed-commitment pricing LP | 1,129.297 |
| Initial result serialization | 0.986 |
| Final independent verification | 8.551 |
| End to end | 1,267.290 |

D+T completed in one scenario-generation round. Its base-only restricted master was already
correctively feasible for all 328 source contingencies, so it added no contingency blocks and did
not re-solve the master.

## Conclusion

Fresh presolved IPM is not the better pricing default for this 2,020-bus formulation. HiPO and IPX
failed to create an accurate feasible basis, after which simplex repeated the same 751,193-iteration
path as the baseline. The existing fresh presolved simplex configuration remains faster and keeps
the same independently verified commitment, dispatch, prices, and security result.

## Local artifact identity

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `result.json` | 11,608,312 | `29bea5335d557be52a3f58e3ef0a68b824045f438611ddbb6c8b4a86b261bee8` |
| `primary-checkpoint.json` | 4,942 | `17b0ce810c017ce4fed53466eabd15e4653d7601a7eefab649348162ab243c30` |
| `primary-primal.npz` | 9,276,600 | `a26b0dfdb689b765d4a0444d07628082b0aa4b8387e4587b2ac570f834d41d13` |
| `pricing-primal.npz` | 9,889,125 | `379bdfd26043e85a88ad8297d9927baccb282f50d9edef3a6c91b5dbbe2d538b` |

These artifacts are local at
`C:\Users\thoma\Documents\goc2-dc-scopf-cpu\results\experimental-2020-dt-ipm-pricing`. They were
not copied to OneDrive and are excluded from Git by the repository contract.
