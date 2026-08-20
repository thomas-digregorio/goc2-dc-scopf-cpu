# C2S6N00617 simplex primary with resident hot-start pricing

## Registered run

- Configuration: `configs/GOC2-DC-D1-CORRECTIVE-v2-617-simplex-hot-pricing.json`
- Frozen solve commit: `8581a038dff899d760159fc038e5a1a1c110ee6c`
- Result: `results/official-617-simplex-root-hot-pricing-cold/result.json`
- Baseline: `results/official-617-primary-only-cold/result.json`
- Cold full-run count: one
- HiGHS: 1.15.1, explicit `mip_lp_solver=simplex`
- Acceptance: PASS for the primary checkpoint, pricing LP, price-dual consistency, and
  independent exhaustive verification of all 815 source contingencies and 816 states.

The canonical model builder and formulation were unchanged. The run used the same source,
matrix, 1e-3 MIP gap, tolerances, seed, presolve setting, and thread setting as the saved
baseline. Only the explicit primary LP method, required resident pricing hot start, and result
paths differ.

## Results

| Metric | Resident hot-start run | Saved cold-pricing baseline | Change |
|---|---:|---:|---:|
| Primary wall time | 1,504.533 s | 1,290.423 s | +16.59% |
| Primary objective | -$227,104.8884044663 | -$227,104.8884044663 | identical |
| Primary dual bound | -$227,130.7094162390 | -$227,130.7094162390 | identical |
| Certified relative gap | 0.0001136964 | 0.0001136964 | identical |
| Primary nodes | 1 | 1 | identical |
| Primary simplex iterations | 626,154 | 626,154 | identical |
| Pricing wall time | 825.633 s | 314.697 s | +162.36% |
| Pricing simplex iterations | 56,389 | 540,996 | -89.58% |
| Pricing objective | -$227,104.8884044696 | -$227,104.8884044673 | numerical tolerance |
| End-to-end active time | 2,353.722 s | 1,638.284 s | +43.67% |
| Peak RSS | 5,217,300,480 bytes | 5,740,724,224 bytes | -9.12% |

The saved baseline used a resumed post-processing stage after retaining its primary checkpoint;
its `end_to_end_active` value combines the two active portions. Primary and pricing solver wall
times are the cleaner stage-level comparison.

## Hot-start acceptance

- The resident HiGHS model was reused.
- All 230,112 commitment/startup/shutdown columns were fixed successfully.
- All 76,704 integer columns were relaxed successfully.
- The MIP solve did not expose a valid reusable basis.
- HiGHS accepted the complete 1,851,891-column verified primary vector with
  `HighsStatus.kOk`.
- The supplied solution was value-valid before the pricing run.
- HiGHS constructed a useful basis and therefore skipped solver presolve.
- The resulting basis initially had 638,499 Phase-I primal infeasibilities. Repairing that
  unpresolved full-model basis required 56,389 dual-simplex iterations and 825.633 seconds.

Thus, the start was genuinely supplied and accepted, and it reduced iteration count by 89.58%,
but it made pricing 2.62 times slower. Skipping presolve left each iteration operating on the full
2,567,696-row, 1,851,891-column LP, overwhelming the iteration-count reduction.

## Solution and verification

- The complete primary primal arrays are bit-for-bit identical to the baseline, including all
  816-state commitment, generation, load, branch-flow, angle, startup, and shutdown values.
- Base commitment: 81 of 94 generators committed; 76 produce power.
- Total base dispatch: 6,636.765573 MW.
- Base fixed-commitment prices range from $95.509999999993 to $95.510000000026/MWh, with mean
  $95.510000000001/MWh. Maximum price difference from the baseline is
  4.30e-11 $/MWh.
- Maximum model residual: 6.513698469e-9 p.u.
- Maximum exhaustive security violation: 6.508983574e-9 p.u.
- Price/dual consistency error: 0.0 $/MWh.
- All acceptance tolerances pass.

The contingency-state pricing recourse variables differ from the cold pricing solution because
the fixed-commitment pricing LP has alternate optima in those non-priced states. Base dispatch and
prices agree to numerical precision, commitment is identical, both pricing objectives agree to
solver tolerance, and both complete solutions pass independent verification.

## Conclusion

This implementation proves that the resident model and complete primary solution reach HiGHS
pricing and are accepted. It does not provide a speedup. A useful next design would need a valid
reusable simplex basis or a way to retain presolve while mapping the primary solution into the
presolved pricing LP; merely supplying the complete unpresolved primal vector is counterproductive
for this case.
