# C2S6N00617 CPU acceleration ablation protocol

## Frozen comparison boundary

The study uses `C2S6N00617/scenario_001`, the complete 815 supplied contingencies,
the `GOC2-DC-D1-CORRECTIVE-v2` mathematical contract, exact source limits and
cost/benefit curves, HiGHS, a `1e-3` requested MIP gap, and the existing independent
checker. Fixed-commitment pricing remains a fresh presolved simplex LP with no basis or
primal start unless the solver-tuning factor changes the simplex implementation itself.

Each cell is run once in a new process. The boundary begins before source ingestion and
ends after exhaustive verification and final serialization. The hard limit is 1,800
seconds. The primary must leave 340 seconds for pricing and checks; pricing must leave 15
seconds for final verification and serialization. A stopped or uncertified cell is a
failed cell and is never automatically retried.

The restored-default control (`0000`) was deliberately run first at commit
`b4fc82f32085c49f863bdcfa2e7b5841fed34fe8`. It completed in 1,605.225 seconds,
returned objective `-227104.888404466`, lower bound `-227130.709416239`, certified gap
`0.00011369641558183`, and passed all 815 contingencies with maximum security violation
`6.5089835743492586e-09` p.u. Optional treatment code is gated off and a byte-identity
test proves that cell `0000` builds the same tiny canonical matrix as the restored default.

## Factors

The cell code is `DICT`:

- `D` — exact contingency scenario generation. Solve a reduced master; independently
  solve all 815 corrective feasibility subproblems with the proposed base decision fixed;
  add every infeasible contingency's complete canonical block; repeat. Success requires
  a final exhaustive screen and a master lower bound within `1e-3` of the feasible
  incumbent.
- `I` — internally generated incumbent. Within a fixed 120-second sub-budget, use only
  source prior commitment plus the same scenario-generation feasibility logic to build a
  complete secure primal. If successful, submit all canonical columns as a MIP start. The
  construction time is included. No saved optimizer solution is read.
- `C` — strong valid inequalities. Add redundant system-capacity, aggregate ramp, and 32
  deterministic weakest-single-bus cut-set inequalities per state. Every row follows
  algebraically from existing nodal balance, branch bounds, PMIN/PMAX, or ramp rows.
- `T` — solver/runtime tuning. Use HiGHS PAMI parallel dual simplex
  (`simplex_strategy=3`, `simplex_max_concurrency=8`, `parallel=on`) with 24 HiGHS
  threads and `OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1` set before
  Python starts.

No factor eliminates branch-flow variables, performs model-side presolve, uses a
Schur-complement solver, changes a source constraint, uses a commercial solver, or uses a
GPU.

## Registered cells and order

After the completed `0000` control, run the four singletons in factor order, then every
pair, every triple, and the all-factor cell:

```text
1000 0100 0010 0001
1100 1010 1001 0110 0101 0011
1110 1101 1011 0111
1111
```

All 15 treatment configurations are stored under `configs/ablation/`. The study reports
total time, stage times, objective, bound/gap, iterations/nodes, incumbent-generation
status, decomposition rounds and active contingencies, valid-cut count, commitment,
dispatch, prices, residuals, exhaustive security, and peak memory. Speed comparisons use
end-to-end wall time; uncertified results are never ranked as successful speedups.
