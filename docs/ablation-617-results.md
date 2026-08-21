# C2S6N00617 CPU acceleration ablation results

## Outcome

The complete registered `DICT` factorial finished with one cold attempt per cell and no
retries. Twelve cells returned a certified solution and passed the independent exhaustive
check of all 815 supplied contingencies. Four cells reached their registered primary-stage
limit and were correctly excluded from speedup rankings. Every end-to-end attempt remained
below 1,800 seconds.

The fastest certified cell was `1001` (`D+T`) at **288.530 seconds** end to end. Relative
to the restored-default control's 1,605.225 seconds, this is a **5.563x system speedup** and
an **82.026% wall-time reduction**. Its primary phase took 56.041 seconds and its fresh
fixed-commitment pricing LP took 213.293 seconds. Pricing therefore remained the largest
component at 73.924% of end-to-end time.

The fastest cell that reproduced the control's commitment, dispatch, and base-bus price
vector was `1011` (`D+C+T`) at **335.312 seconds**, a **4.787x speedup** and **79.111%
wall-time reduction**.

After review, the requested `1e-3` certificate was accepted as the governing quality gate and
`1001` (`D+T`) was promoted to the repository's operational default. The control and all frozen
ablation configurations remain unchanged as historical evidence.

This is a derived lossless-DC benchmark result. It is not an official GO Challenge score
or a PJM/CAISO market or reliability result.

## Factor legend

The four-bit cell code is `DICT`:

- `D`: exact contingency scenario generation with all 815 source contingencies screened.
- `I`: internally generate a complete secure incumbent and submit it as a MIP start.
- `C`: add 55,488 redundant strong valid inequalities.
- `T`: use HiGHS PAMI parallel dual simplex with 24 HiGHS threads, concurrency 8, and
  single-threaded BLAS/OpenMP runtimes.

All cells preserve the same source-derived mathematical contract, complete contingency
set, 1e-3 requested MIP gap, and independent checker. The timeout rows' starred primary
times are the solver-stage times captured at the clean deadline return, not successful
primary totals.

## Full result table

| Cell | Result | E2E s | Speedup | Primary s | Pricing s | Objective | Bound | Gap | On | Max residual p.u. | Max security p.u. | Peak GiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0000 | PASS | 1605.23 | 1.00x | 1268.92 | 317.00 | -227104.888 | -227130.709 | 0.0114% | 81 | 6.51E-09 | 6.51E-09 | 5.37 |
| 1000 | PASS | 360.77 | 4.45x | 56.16 | 285.47 | -227041.742 | -227143.686 | 0.0449% | 82 | 3.09E-09 | 1.37E-09 | 3.13 |
| 0100 | PASS | 1557.85 | 1.03x | 1222.23 | 316.62 | -227104.888 | -227130.709 | 0.0114% | 81 | 6.51E-09 | 6.51E-09 | 6.23 |
| 0010 | TIMEOUT | 1539.85 | — | 1530.36* | — | — | -227143.686 | — | — | — | — | 5.07 |
| 0001 | PASS | 1407.76 | 1.14x | 1161.52 | 227.16 | -227104.888 | -227130.709 | 0.0114% | 81 | 6.51E-09 | 6.51E-09 | 6.13 |
| 1100 | PASS | 419.47 | 3.83x | 114.61 | 285.72 | -227041.742 | -227143.686 | 0.0449% | 82 | 3.09E-09 | 1.37E-09 | 3.15 |
| 1010 | PASS | 414.77 | 3.87x | 68.24 | 326.40 | -227104.888 | -227143.686 | 0.0171% | 81 | 7.24E-10 | 1.80E-10 | 3.43 |
| 1001 | PASS | 288.53 | 5.56x | 56.04 | 213.29 | -227041.742 | -227143.686 | 0.0449% | 82 | 3.09E-09 | 1.37E-09 | 3.22 |
| 0110 | TIMEOUT | 1461.68 | — | 1376.85* | — | -221146.941 | -227143.686 | 2.7117% | — | — | — | 5.15 |
| 0101 | PASS | 1492.36 | 1.08x | 1244.83 | 228.32 | -227104.888 | -227130.709 | 0.0114% | 81 | 6.51E-09 | 6.51E-09 | 6.20 |
| 0011 | TIMEOUT | 1543.00 | — | 1533.54* | — | — | -227143.686 | — | — | — | — | 5.06 |
| 1110 | PASS | 487.36 | 3.29x | 141.30 | 325.81 | -227104.888 | -227143.686 | 0.0171% | 81 | 7.24E-10 | 1.80E-10 | 3.39 |
| 1101 | PASS | 348.79 | 4.60x | 115.25 | 214.43 | -227041.742 | -227143.686 | 0.0449% | 82 | 3.09E-09 | 1.37E-09 | 3.23 |
| 1011 | PASS | 335.31 | 4.79x | 68.24 | 246.91 | -227104.888 | -227143.686 | 0.0171% | 81 | 7.24E-10 | 1.80E-10 | 3.44 |
| 0111 | TIMEOUT | 1461.69 | — | 1378.27* | — | -221146.941 | -227143.686 | 2.7117% | — | — | — | 5.14 |
| 1111 | PASS | 408.85 | 3.93x | 141.44 | 247.27 | -227104.888 | -227143.686 | 0.0171% | 81 | 7.24E-10 | 1.80E-10 | 3.50 |

All twelve `PASS` rows completed fixed-commitment pricing and independently verified all
816 states: the base state plus 815 source contingencies. A timeout row is not a feasible
or certified benchmark result even where a partial feasible incumbent was retained.

## Commitment, dispatch, and pricing comparison

The successful cells form two numerical solution classes.

### Control-equivalent 81-unit class

Cells `0000`, `0100`, `0001`, `1010`, `0101`, `1110`, `1011`, and `1111` have the
same 94-entry commitment vector as the control. Their dispatch vectors match within
`4.44e-11` MW and their 617 base-bus prices match within `1.83e-10` USD/MWh. The
control's base-bus prices are uniformly about 95.510 USD/MWh.

### Alternate certified 82-unit class

Cells `1000`, `1100`, `1001`, and `1101` have the same alternate solution. Relative
to the control, exactly one additional generator is committed and five generator
dispatches change:

| Generator source identity | Control u | Alternate u | Control MW | Alternate MW | Delta MW |
| --- | ---: | ---: | ---: | ---: | ---: |
| bus 466, id 1 | 0 | 1 | 0.000000 | 230.890000 | 230.890000 |
| bus 497, id 1 | 1 | 1 | 158.313973 | 92.540000 | -65.773973 |
| bus 535, id 1 | 1 | 1 | 296.920000 | 265.820000 | -31.100000 |
| bus 544, id 1 | 1 | 1 | 232.002800 | 187.086773 | -44.916027 |
| bus 598, id 1 | 1 | 1 | 285.700000 | 196.600000 | -89.100000 |

All 617 base-bus prices move uniformly from about 95.510 to 72.987 USD/MWh, a
`-22.523` USD/MWh shift. The alternate objective is 63.146717 higher for this
minimization model, a 0.027805% difference from the control objective. It is nevertheless
a valid requested-gap result: its certified MIP gap is 0.044901%, below 0.1%.

The model is unchanged between these two classes. The distinction comes from which
near-optimal incumbent HiGHS reaches before the 1e-3 stopping criterion is satisfied.
Consequently, a 1e-3 MIP gap does not guarantee invariant commitment, dispatch, or
fixed-commitment prices across exact algorithms or solver settings.

## Factor findings

- **D was decisive.** Every D cell passed all 815 independent feasibility subproblems in
  its first screen, so no contingency block had to be activated and no second master
  round was needed. This is still exhaustive checking, not contingency omission. In the
  fastest cell, the master plus all screens consumed about 43.85 solver seconds and the
  entire primary phase consumed 56.04 seconds.
- **T was consistently useful wherever its paired cells both completed.** It reduced
  control time by 197.46 seconds, D time by 72.25 seconds, D+C time by 79.46 seconds,
  and D+I+C time by 78.51 seconds.
- **I was accepted correctly but was usually overhead.** The full internally generated
  starts passed HiGHS' row, bound, and integrality checks. I saved 47.38 seconds versus
  control in isolation, but added roughly 59 to 74 seconds to the successful D
  combinations and did not cure C's lower-bound bottleneck.
- **C was harmful for runtime in this experiment.** Without D, every C-containing cell
  timed out in the strengthened extensive root LP after 718,564 simplex iterations.
  With D, C remained certifiable but added screening/pricing work. It also steered HiGHS
  to the lower 81-unit incumbent before the requested gap was met.

## Timeout interpretation

Cells `0010` and `0011` reached a lower bound of `-227143.685516` but had no incumbent.
Cells `0110` and `0111` accepted a feasible internally generated incumbent with objective
`-221146.941487`, but their gap remained 2.711656%. Pricing and final verification were
therefore correctly skipped. These are computational timeouts, not infeasibility claims.

## Reproducibility boundary

- Source scenario: `C2S6N00617/scenario_001`.
- Source hashes:
  - `case.raw`: `ab7d2b87c9e34d070098bf9e578554646a3aca81e3dc86c717c5efa3f35120a9`
  - `case.con`: `09bd85c1e71a713740abc925603d2b138a8cb6a5a5be046b1349d5ed0ff382bd`
  - `case.json`: `19bda25a8c14d7146d8680a0025a901a261827c06fdd6fb29c720f180558aa89`
- Control commit: `b4fc82f32085c49f863bdcfa2e7b5841fed34fe8`.
- Treatment commit: `fb21175656d00afb31f2ff9e94e049258431a7c0`.
- Host: Windows 11, 24 logical/physical CPUs, 33.75 GB reported memory.
- Raw result JSON remains local under `results/official-617-simplex-fresh-pricing-cold-v2/`
  and `results/ablation-617/cell-*/`; results are intentionally gitignored.

The control was run first, before the treatment implementation commit. A component test
proves the gated zero-factor canonical matrix is byte-identical to the restored default,
but the control and treatment timings are not from the exact same executable commit. This
is disclosed as a timing-study limitation; the control was not rerun because the protocol
allowed one attempt per cell and explicitly required the control first.
