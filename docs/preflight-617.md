# 617-bus preflight

The registered source is C2S6N00617/scenario_001, selected by the frozen
lexicographic rule before optimization. Hash verification and parsing report:

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
| Columns | 2,261,836 |
| Commitment binaries | 76,704 |
| Rows | 3,387,586 |
| Nonzeros | 9,530,711 |
| Canonical matrix buffers | 195,670,604 bytes |

On the development laptop, canonical construction took about 7.0 seconds and a no-solve pass into
HiGHS took about 1.1 seconds. These are development preflight observations, not benchmark timings.
Seven tiny/component tests and lint pass. No full-case optimization has been run as part of
preflight.

