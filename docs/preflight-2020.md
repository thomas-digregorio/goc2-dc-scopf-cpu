# 2,020-bus preflight

The registered source is `C2S7N02020/scenario_001`, selected by the frozen source-family and
source-directory ordering rule before optimization. Hash verification and parsing report:

- 2,020 buses, 1,392 source-authorized responsive loads, and 194 generators;
- all 194 generators online at the immutable source prior point;
- 2,856 active lines and transformers;
- 321 source branch contingencies and 7 source generator contingencies;
- zero missing, offline-target, multi-event, untranslated, or islanding contingencies;
- zero non-unit transformer taps and one nonzero phase shift;
- one source impedance-correction table applied at the frozen operating point;
- zero active fixed-shunt conductance records;
- no source branch angle-difference limits in this profile.

All source `RATEC` values happen to equal `RATEA` in this scenario. The model keeps the two fields
and applies them by state; it does not invent an emergency multiplier.

The complete extensive matrix, built without optimizing, contains:

| Quantity | Value |
|---|---:|
| Columns | 2,322,377 |
| Commitment binaries | 63,826 |
| Rows | 3,095,343 |
| Nonzeros | 8,519,921 |
| Canonical matrix buffers | 176,527,292 bytes |

On the development laptop, canonical construction took about 6.38 seconds and a no-solve pass
into HiGHS took about 1.02 seconds. These are development preflight observations, not benchmark
timings. Component tests and lint passed before the cold run was registered.
