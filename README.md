# GOC2-DC-D1-CORRECTIVE-v2

This repository implements a CPU, lossless-DC, GO Challenge 2-derived corrective
security-constrained commitment and dispatch benchmark. It preserves source generator and
contingency semantics but is neither the official AC challenge model nor a complete reproduction
of an ISO market or reliability assessment.

The first registered case is the lexicographically first scenario in the public 617-bus
Challenge 2 Sandbox 6 archive: `C2S6N00617/scenario_001`. After that case passed its acceptance
gates and the user approved the next scale, the lexicographically first standard C2S7 2,020-bus
scenario, `C2S7N02020/scenario_001`, was frozen before any optimization. Source URLs, identities,
and hashes are immutable for both cases.

The public [Challenge 2 OEDI catalog](https://data.openei.org/submissions/6197) contains multiple
event and sandbox families rather than one single size ladder. The C2S7 family contains 617, 793,
2,020, 2,312, 4,102, 4,230, 5,752, 6,473, 8,032, 9,459, 9,460, 9,462, 12,209, 14,212, 24,465, and
31,777-bus networks. This project advances from 617 directly to the previously registered
2,020-bus target; it does not imply that the different-family 768-bus trial case or C2S7 793-bus
case do not exist.

## Contract

- one prior point, one preventive base state, and every source corrective state (815 for the
  registered 617-bus case and 328 for the registered 2,020-bus case);
- exact source PMIN/PMAX, commitment-change permissions, ramps, costs, demand bounds, and benefits;
- source branch and generator contingencies only;
- `RATEA` in the base state and `RATEC` in contingency states;
- fixed source topology except for the explicitly outaged device;
- no load shedding, generation spillage, overload slack, or automatic feasibility repair;
- exact primary scenario generation: solve a reduced master, screen every complete corrective
  subproblem, add every infeasible contingency's canonical block, and repeat;
- immediate, durable primary-solution checkpointing;
- a separate exhaustive checker that rereads the immutable source files before pricing;
- a fixed-commitment pricing LP only after the independently checked primary passes;
- by default, HiGHS PAMI parallel dual simplex with 24 HiGHS threads and single-threaded numerical
  runtimes, followed by a fresh simplex pricing LP with presolve and no basis or primal start;
- a hard 1,800-second end-to-end budget that reserves time for pricing and verification.

The source curves are synthetic GO Challenge curves, not submitted ISO offers. Reported nodal
prices are fixed-commitment, lossless-DC, security-constrained diagnostics—not PJM or CAISO
settlement LMPs. Raw base balance-row duals are retained, and the checker verifies the documented
HiGHS dual-to-$/MWh sign and unit conversion.

See [docs/model-contract.md](docs/model-contract.md), the frozen
[617-bus source manifest](docs/source-manifest.json), and the frozen
[2,020-bus source manifest](docs/source-manifest-2020.json) for the registered details. The
non-solving [617-bus preflight](docs/preflight-617.md) and
[2,020-bus preflight](docs/preflight-2020.md) record source translation and matrix-size gates.
The completed 16-cell CPU acceleration study is reported in
[docs/ablation-617-results.md](docs/ablation-617-results.md), with machine-readable summary
metrics in [docs/ablation-617-results.csv](docs/ablation-617-results.csv). The single authorized
[2,020-bus D+T result](docs/dt-2020-result.md) is reported separately.

## Local-only setup

The CLI rejects any repository, source, result, cache, environment, scratch, or temporary path
containing `OneDrive` (case-insensitive). The intended Windows root is:

```text
C:\Users\thoma\Documents\goc2-dc-scopf-cpu
```

Initialize dependencies and fetch the immutable archive with:

```powershell
pwsh scripts/bootstrap.ps1
pwsh scripts/fetch-617.ps1
pwsh scripts/fetch-2020.ps1
```

Development uses only tiny fixtures. After all preflight gates pass, each explicitly authorized
`benchmark` invocation is cold and records a run lock so an accidental repetition is refused.
If a post-primary serialization, verification, or pricing failure occurs, `resume` may continue
from the hashed primary checkpoint; it refuses to rerun the MILP and records the separate
post-processing commit.

The default configuration is
`configs/GOC2-DC-D1-CORRECTIVE-v2-617-dt-default.json`. It is the certified D+T profile selected
after the completed acceleration ablation. The registered 2,020-bus scale-up uses the same profile
in `configs/GOC2-DC-D1-CORRECTIVE-v2-2020-dt.json`; changing the network does not change an ablation
factor. The CLI applies its one-thread BLAS/OpenMP policy before importing numerical libraries, so
no shell environment setup is required. The prior extensive
simplex control remains frozen at
`configs/GOC2-DC-D1-CORRECTIVE-v2-617-simplex-fresh-pricing.json`. Prior experiment configurations
and their hashes remain frozen. Resident-model pricing hot starts are retained only in explicitly
named experimental configurations and are not the default path.

## Attribution

The benchmark is derived from public ARPA-E Grid Optimization Competition Challenge 2 data.
Parsing uses the public-domain
[GOCompetition/C2DataUtilities](https://github.com/GOCompetition/C2DataUtilities) repository,
pinned as a Git submodule. HiGHS and the Python dependencies retain their own licenses. The
optional `highspy[extras]` installation supplies HiPO's AMD, BLAS, METIS, and RCM dependencies and
is Apache-2.0 licensed; the base `highspy` package is MIT licensed. No project license is granted by
this repository at this time.
