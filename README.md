# GOC2-DC-D1-CORRECTIVE-v2

This repository implements a CPU, lossless-DC, GO Challenge 2-derived corrective
security-constrained commitment and dispatch benchmark. It preserves source generator and
contingency semantics but is neither the official AC challenge model nor a complete reproduction
of an ISO market or reliability assessment.

The initial registered case is the lexicographically first scenario in the public 617-bus
Challenge 2 Sandbox 6 archive: `C2S6N00617/scenario_001`. The source selection, URLs, identities,
and hashes were frozen before any optimization result was observed. The 2,020-bus case is out of
scope until the 617-bus acceptance gates pass and the user approves it.

## Contract

- one prior point, one preventive base state, and all 815 source corrective states;
- exact source PMIN/PMAX, commitment-change permissions, ramps, costs, demand bounds, and benefits;
- source branch and generator contingencies only;
- `RATEA` in the base state and `RATEC` in contingency states;
- fixed source topology except for the explicitly outaged device;
- no load shedding, generation spillage, overload slack, or automatic feasibility repair;
- one native HiGHS primary extensive MILP with no corrective-movement secondary objective;
- immediate, durable primary-solution checkpointing;
- a separate exhaustive checker that rereads the immutable source files before pricing;
- a fixed-commitment pricing LP only after the independently checked primary passes;
- by default, an explicit simplex primary with solver presolve on, followed by a fresh simplex
  pricing LP with solver presolve on and no basis or primal start.

The source curves are synthetic GO Challenge curves, not submitted ISO offers. Reported nodal
prices are fixed-commitment, lossless-DC, security-constrained diagnostics—not PJM or CAISO
settlement LMPs. Raw base balance-row duals are retained, and the checker verifies the documented
HiGHS dual-to-$/MWh sign and unit conversion.

See [docs/model-contract.md](docs/model-contract.md) and
[docs/source-manifest.json](docs/source-manifest.json) for the frozen details. The non-solving
[617-bus preflight](docs/preflight-617.md) records source translation and matrix-size gates.
The completed 16-cell CPU acceleration study is reported in
[docs/ablation-617-results.md](docs/ablation-617-results.md), with machine-readable summary
metrics in [docs/ablation-617-results.csv](docs/ablation-617-results.csv).

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
```

Development uses only tiny fixtures. After all preflight gates pass, each explicitly authorized
`benchmark` invocation is cold and records a run lock so an accidental repetition is refused.
If a post-primary serialization, verification, or pricing failure occurs, `resume` may continue
from the hashed primary checkpoint; it refuses to rerun the MILP and records the separate
post-processing commit.

The default configuration is
`configs/GOC2-DC-D1-CORRECTIVE-v2-617-simplex-fresh-pricing.json`. Prior experiment
configurations and their hashes remain frozen. Resident-model pricing hot starts are retained only
in explicitly named experimental configurations and are not the default path.

## Attribution

The benchmark is derived from public ARPA-E Grid Optimization Competition Challenge 2 data.
Parsing uses the public-domain
[GOCompetition/C2DataUtilities](https://github.com/GOCompetition/C2DataUtilities) repository,
pinned as a Git submodule. HiGHS and the Python dependencies retain their own licenses. The
optional `highspy[extras]` installation supplies HiPO's AMD, BLAS, METIS, and RCM dependencies and
is Apache-2.0 licensed; the base `highspy` package is MIT licensed. No project license is granted by
this repository at this time.
