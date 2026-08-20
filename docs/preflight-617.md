# 617-bus preflight

The registered source is C2S6N00617/scenario_001, selected by the frozen
source-directory ordering rule before optimization. Hash verification and parsing report:

- 617 buses, 409 source-authorized responsive loads, and 94 generators;
- 82 prior-online generators;
- 703 active non-transformer lines and 163 active transformers;
- 751 source branch contingencies and 64 source generator contingencies;
- zero missing, offline-target, multi-event, or islanding contingencies;
- three non-unit transformer taps and three nonzero phase shifts;
- two active source impedance-correction tables at the frozen operating point;
- zero active fixed-shunt conductance records;
- no source branch angle-difference limits in this profile.

All source RATEC values happen to equal RATEA in this scenario. The model keeps the two fields
and applies them by state; it does not invent an emergency multiplier.

The complete extensive matrix, built without optimizing, contains:

| Quantity | Value |
|---|---:|
| Columns | 1,851,891 |
| Commitment binaries | 76,704 |
| Rows | 2,567,696 |
| Nonzeros | 7,071,041 |
| Canonical matrix buffers | 146,477,204 bytes |

The v2 primary formulation removes 409,945 corrective-deviation columns and 819,890 absolute-value
rows that existed only for the deleted secondary objective. Their removal does not change the
primary feasible projection or primary objective.

On the development laptop, canonical construction took about 5.9 seconds and a no-solve pass into
HiGHS took about 0.84 seconds. These are development preflight observations, not benchmark timings.
Eight tiny/component tests and lint pass. No full-case optimization has been run as part of
preflight.
