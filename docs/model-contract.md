# Model contract

Profile: `GOC2-DC-D1-CORRECTIVE-v1`

The immutable prior point supplies generator commitment and active dispatch. It is neither an
optimized period nor a solver start. The MILP chooses one preventive base state and one conditional
corrective state per source contingency. A corrective state certifies the modeled operating point
after the source contingency-response interval; it says nothing about instantaneous, transient,
frequency, voltage, or AC security.

For each generator and modeled state, exact source limits apply:

```text
PMIN[g] * u[g,k] <= P[g,k] <= PMAX[g] * u[g,k]
```

Startup and shutdown permissions are directional and are taken from `suqual`, `sdqual`,
`suqualctg`, and `sdqualctg`. Prior-to-base and base-to-contingency ramps use the source interval
durations. A generator outage overrides normal status-transition rules for the failed generator.
No generator may reverse a base startup with a contingency shutdown, or a base shutdown with a
contingency startup, matching the official source semantics.

Active load is dispatchable only where the source supplies bounds and benefit blocks. It remains
within the exact `tmin * PL` and `tmax * PL` domain and the source active-power response limits.
There is no involuntary load-shedding variable.

The lossless DC branch equations use source reactance, fixed tap magnitude, and fixed phase shift.
Active fixed-shunt conductance is represented at 1.0 p.u. voltage. Reactive quantities, voltage
magnitudes, resistance losses, reactive shunts, AC recovery, and discretionary switching are
excluded.

The primary objective minimizes base production and commitment cost minus source-authorized base
load benefit. Contingency states are feasibility certificates. At the registered MIP resolution,
a second solve constrains the primary objective to the primary incumbent and minimizes normalized
absolute corrective generation/load movement plus contingency startups. This intentionally differs
from official Challenge 2 scoring.

After all binaries are fixed, the complete continuous formulation is resolved. Negative base
balance-row duals, converted from interval dollars per p.u. to dollars per MWh, are reported as
fixed-commitment, lossless-DC, security-constrained nodal prices.

