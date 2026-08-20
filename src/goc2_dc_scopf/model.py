from __future__ import annotations

from array import array
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from .source import CaseData

INF = float("inf")


@dataclass(frozen=True)
class StateLayout:
    state_index: int
    offset: int
    num_bus: int
    num_gen: int
    num_load: int
    num_branch: int

    @property
    def theta_start(self) -> int:
        return self.offset

    @property
    def pg_start(self) -> int:
        return self.theta_start + self.num_bus

    @property
    def load_start(self) -> int:
        return self.pg_start + self.num_gen

    @property
    def flow_start(self) -> int:
        return self.load_start + self.num_load

    @property
    def u_start(self) -> int:
        return self.flow_start + self.num_branch

    @property
    def startup_start(self) -> int:
        return self.u_start + self.num_gen

    @property
    def shutdown_start(self) -> int:
        return self.startup_start + self.num_gen

    @property
    def stop(self) -> int:
        return self.shutdown_start + self.num_gen

    def theta(self, index: int) -> int:
        return self.theta_start + index

    def pg(self, index: int) -> int:
        return self.pg_start + index

    def load(self, index: int) -> int:
        return self.load_start + index

    def flow(self, index: int) -> int:
        return self.flow_start + index

    def u(self, index: int) -> int:
        return self.u_start + index

    def startup(self, index: int) -> int:
        return self.startup_start + index

    def shutdown(self, index: int) -> int:
        return self.shutdown_start + index


@dataclass(frozen=True)
class VariableLayout:
    states: tuple[StateLayout, ...]
    generator_segment_columns: tuple[tuple[int, ...], ...]
    load_segment_columns: tuple[tuple[int, ...], ...]
    num_columns: int


@dataclass(frozen=True)
class ModelMetadata:
    base_balance_rows: tuple[int, ...]
    balance_row_starts: tuple[int, ...]
    primary_objective_name: str
    valid_inequality_rows: tuple[int, ...] = ()


class SparseRows:
    """Compact CSR-like row builder using typed buffers instead of Python tuples."""

    def __init__(self) -> None:
        self.starts = array("q", [0])
        self.indices = array("i")
        self.values = array("d")
        self.lower = array("d")
        self.upper = array("d")

    @property
    def num_rows(self) -> int:
        return len(self.lower)

    @property
    def num_nonzeros(self) -> int:
        return len(self.values)

    def add(
        self,
        columns: Sequence[int] | Iterable[int],
        coefficients: Sequence[float] | Iterable[float],
        lower: float,
        upper: float,
    ) -> int:
        row = len(self.lower)
        if not isinstance(columns, Sequence):
            columns = tuple(columns)
        if not isinstance(coefficients, Sequence):
            coefficients = tuple(coefficients)
        if len(columns) != len(coefficients):
            raise ValueError("Sparse row columns and coefficients have different lengths")
        for column, coefficient in zip(columns, coefficients, strict=True):
            if coefficient == 0.0:
                continue
            self.indices.append(int(column))
            self.values.append(float(coefficient))
        self.lower.append(float(lower))
        self.upper.append(float(upper))
        self.starts.append(len(self.indices))
        return row

    def numpy_buffers(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return (
            np.frombuffer(self.starts, dtype=np.int64),
            np.frombuffer(self.indices, dtype=np.int32),
            np.frombuffer(self.values, dtype=np.float64),
            np.frombuffer(self.lower, dtype=np.float64),
            np.frombuffer(self.upper, dtype=np.float64),
        )


@dataclass
class CanonicalModel:
    case: CaseData
    layout: VariableLayout
    column_lower: np.ndarray
    column_upper: np.ndarray
    primary_cost: np.ndarray
    integer_columns: np.ndarray
    rows: SparseRows
    metadata: ModelMetadata

    def statistics(self) -> dict[str, int | float]:
        return {
            "columns": self.layout.num_columns,
            "integer_columns": int(self.integer_columns.size),
            "rows": self.rows.num_rows,
            "nonzeros": self.rows.num_nonzeros,
            "valid_inequality_rows": len(self.metadata.valid_inequality_rows),
            "matrix_storage_bytes": (
                len(self.rows.starts) * 8
                + len(self.rows.indices) * 4
                + len(self.rows.values) * 8
                + len(self.rows.lower) * 8
                + len(self.rows.upper) * 8
            ),
        }

    def maximum_valid_inequality_violation(self, values: np.ndarray) -> float:
        if values.shape != (self.layout.num_columns,):
            raise ValueError("Canonical value vector has the wrong width")
        starts, indices, coefficients, lower, upper = self.rows.numpy_buffers()
        maximum = 0.0
        for row in self.metadata.valid_inequality_rows:
            begin = int(starts[row])
            end = int(starts[row + 1])
            activity = float(np.dot(coefficients[begin:end], values[indices[begin:end]]))
            maximum = max(maximum, float(lower[row]) - activity, activity - float(upper[row]))
        return max(0.0, maximum)


def _make_layout(case: CaseData) -> VariableLayout:
    nb = len(case.buses)
    ng = len(case.generators)
    nl = len(case.loads)
    ne = len(case.branches)
    block_size = nb + ng + nl + ne + 3 * ng
    states = tuple(StateLayout(k, k * block_size, nb, ng, nl, ne) for k in range(case.states))
    next_column = case.states * block_size
    generator_segments: list[tuple[int, ...]] = []
    for generator in case.generators:
        columns = tuple(range(next_column, next_column + len(generator.cost_segments)))
        generator_segments.append(columns)
        next_column += len(columns)
    load_segments: list[tuple[int, ...]] = []
    for load in case.loads:
        columns = tuple(range(next_column, next_column + len(load.benefit_segments)))
        load_segments.append(columns)
        next_column += len(columns)
    return VariableLayout(
        states,
        tuple(generator_segments),
        tuple(load_segments),
        next_column,
    )


def estimate_extensive_size(case: CaseData) -> dict[str, int]:
    layout = _make_layout(case)
    nb = len(case.buses)
    ng = len(case.generators)
    nl = len(case.loads)
    ne = len(case.branches)
    nc = len(case.contingencies)
    base_rows = 1 + nb + ne + 5 * ng + 2 * nl
    contingency_rows = nc * (1 + nb + ne + 9 * ng + 2 * nl)
    segment_rows = ng + nl
    return {
        "columns": layout.num_columns,
        "integer_columns": case.states * ng,
        "estimated_rows_upper_bound": base_rows + contingency_rows + segment_rows,
    }


def _add_valid_inequalities(
    case: CaseData,
    layout: VariableLayout,
    rows: SparseRows,
    *,
    weakest_bus_count: int,
) -> tuple[int, ...]:
    """Add redundant capacity, ramp, and single-bus cut-set inequalities.

    Every row is implied by existing nodal balances, branch bounds, generator
    PMIN/PMAX, or generator ramp rows. They strengthen the LP representation
    without changing the integer-feasible set.
    """

    bus_generators: list[list[int]] = [[] for _ in case.buses]
    bus_loads: list[list[int]] = [[] for _ in case.buses]
    bus_shunt = np.zeros(len(case.buses), dtype=np.float64)
    for g, generator in enumerate(case.generators):
        bus_generators[generator.bus_index].append(g)
    for load_index, load in enumerate(case.loads):
        bus_loads[load.bus_index].append(load_index)
    for shunt in case.fixed_shunts:
        bus_shunt[shunt.bus_index] += shunt.conductance_pu

    added: list[int] = []
    all_buses = tuple(range(len(case.buses)))

    def add_cut_set(
        state: StateLayout,
        buses: Sequence[int],
        capacity: float,
    ) -> None:
        generators = [g for bus in buses for g in bus_generators[bus]]
        loads = [load for bus in buses for load in bus_loads[bus]]
        shunt = float(sum(bus_shunt[bus] for bus in buses))
        columns = [state.u(g) for g in generators] + [state.load(load) for load in loads]
        lower_coefficients = [case.generators[g].pmax_pu for g in generators] + [
            -1.0 for _ in loads
        ]
        upper_coefficients = [case.generators[g].pmin_pu for g in generators] + [
            -1.0 for _ in loads
        ]
        added.append(
            rows.add(columns, lower_coefficients, shunt - capacity, INF)
        )
        added.append(
            rows.add(columns, upper_coefficients, -INF, shunt + capacity)
        )

    for state_index, state in enumerate(layout.states):
        contingency = None if state_index == 0 else case.contingencies[state_index - 1]
        add_cut_set(state, all_buses, 0.0)

        incident_capacity = np.zeros(len(case.buses), dtype=np.float64)
        for branch_index, branch in enumerate(case.branches):
            if contingency is not None and contingency.branch_index == branch_index:
                continue
            limit = branch.normal_limit_pu if state_index == 0 else branch.emergency_limit_pu
            incident_capacity[branch.from_bus_index] += limit
            incident_capacity[branch.to_bus_index] += limit
        candidates: list[tuple[float, int]] = []
        for bus in range(len(case.buses)):
            if not bus_generators[bus] and not bus_loads[bus]:
                continue
            activity = sum(
                max(abs(case.generators[g].pmin_pu), abs(case.generators[g].pmax_pu))
                for g in bus_generators[bus]
            ) + sum(case.loads[load].pmax_pu for load in bus_loads[bus])
            score = incident_capacity[bus] / max(activity, 1e-12)
            candidates.append((score, bus))
        for _, bus in sorted(candidates)[:weakest_bus_count]:
            add_cut_set(state, (bus,), float(incident_capacity[bus]))

        load_columns = [state.load(load) for load in range(len(case.loads))]
        if state_index == 0:
            upper_columns = list(load_columns)
            upper_coefficients = [1.0] * len(load_columns)
            lower_columns = list(load_columns)
            lower_coefficients = [-1.0] * len(load_columns)
            prior_sum = 0.0
            for g, generator in enumerate(case.generators):
                prior_sum += generator.prior_p_pu
                upper_columns.extend((state.u(g), state.startup(g)))
                upper_coefficients.extend(
                    (
                        -generator.ramp_up_base_pu_per_h * case.response_base_hours,
                        -generator.pmin_pu,
                    )
                )
                lower_columns.extend((state.u(g), state.shutdown(g)))
                lower_coefficients.extend(
                    (
                        -generator.ramp_down_base_pu_per_h * case.response_base_hours,
                        -generator.pmax_pu,
                    )
                )
            total_shunt = float(np.sum(bus_shunt))
            added.append(
                rows.add(
                    upper_columns,
                    upper_coefficients,
                    -INF,
                    prior_sum - total_shunt,
                )
            )
            added.append(
                rows.add(
                    lower_columns,
                    lower_coefficients,
                    -INF,
                    total_shunt - prior_sum,
                )
            )
        else:
            base = layout.states[0]
            upper_columns = list(load_columns)
            upper_coefficients = [1.0] * len(load_columns)
            lower_columns = list(load_columns)
            lower_coefficients = [-1.0] * len(load_columns)
            for g, generator in enumerate(case.generators):
                if contingency is not None and contingency.generator_index == g:
                    continue
                upper_columns.extend((base.pg(g), state.u(g), state.startup(g)))
                upper_coefficients.extend(
                    (
                        -1.0,
                        -generator.ramp_up_ctg_pu_per_h * case.response_ctg_hours,
                        -generator.pmin_pu,
                    )
                )
                lower_columns.extend((base.pg(g), state.u(g), state.shutdown(g)))
                lower_coefficients.extend(
                    (
                        1.0,
                        -generator.ramp_down_ctg_pu_per_h * case.response_ctg_hours,
                        -generator.pmax_pu,
                    )
                )
            total_shunt = float(np.sum(bus_shunt))
            added.append(rows.add(upper_columns, upper_coefficients, -INF, -total_shunt))
            added.append(rows.add(lower_columns, lower_coefficients, -INF, total_shunt))

    return tuple(added)


def build_extensive_model(case: CaseData, config: dict) -> CanonicalModel:
    layout = _make_layout(case)
    ncol = layout.num_columns
    lower = np.full(ncol, -INF, dtype=np.float64)
    upper = np.full(ncol, INF, dtype=np.float64)
    primary = np.zeros(ncol, dtype=np.float64)
    integer_columns: list[int] = []
    base = layout.states[0]
    base_mva = case.base_mva
    delta = case.delta_hours

    for state_index, state in enumerate(layout.states):
        lower[state.theta_start : state.pg_start] = -INF
        upper[state.theta_start : state.pg_start] = INF
        contingency = None if state_index == 0 else case.contingencies[state_index - 1]
        for g, generator in enumerate(case.generators):
            lower[state.pg(g)] = min(0.0, generator.pmin_pu)
            upper[state.pg(g)] = max(0.0, generator.pmax_pu)
            lower[state.u(g)] = 0.0
            upper[state.u(g)] = 1.0
            integer_columns.append(state.u(g))
            lower[state.startup(g)] = 0.0
            lower[state.shutdown(g)] = 0.0
            if state_index == 0:
                upper[state.startup(g)] = float(
                    generator.startup_qualified_base * (1 - generator.prior_on)
                )
                upper[state.shutdown(g)] = float(
                    generator.shutdown_qualified_base * generator.prior_on
                )
            elif contingency is not None and contingency.generator_index == g:
                lower[state.pg(g)] = upper[state.pg(g)] = 0.0
                lower[state.u(g)] = upper[state.u(g)] = 0.0
                upper[state.startup(g)] = 0.0
                upper[state.shutdown(g)] = 0.0
            else:
                upper[state.startup(g)] = float(generator.startup_qualified_ctg)
                upper[state.shutdown(g)] = float(generator.shutdown_qualified_ctg)
        for load_index, load in enumerate(case.loads):
            lower[state.load(load_index)] = load.pmin_pu
            upper[state.load(load_index)] = load.pmax_pu
        for branch_index, branch in enumerate(case.branches):
            limit = branch.normal_limit_pu if state_index == 0 else branch.emergency_limit_pu
            if contingency is not None and contingency.branch_index == branch_index:
                limit = 0.0
            lower[state.flow(branch_index)] = -limit
            upper[state.flow(branch_index)] = limit

    for g, generator in enumerate(case.generators):
        for column, segment in zip(
            layout.generator_segment_columns[g], generator.cost_segments, strict=True
        ):
            lower[column] = 0.0
            upper[column] = segment.width_pu
            primary[column] = segment.marginal_per_mwh * base_mva * delta
        primary[base.u(g)] = generator.on_cost_per_h * delta
        primary[base.startup(g)] = generator.startup_cost
        primary[base.shutdown(g)] = generator.shutdown_cost
    for load_index, load in enumerate(case.loads):
        for column, segment in zip(
            layout.load_segment_columns[load_index], load.benefit_segments, strict=True
        ):
            lower[column] = 0.0
            upper[column] = segment.width_pu
            primary[column] = -segment.marginal_per_mwh * base_mva * delta

    rows = SparseRows()
    bus_generators: list[list[int]] = [[] for _ in case.buses]
    bus_loads: list[list[int]] = [[] for _ in case.buses]
    bus_flows: list[list[tuple[int, float]]] = [[] for _ in case.buses]
    bus_shunt = np.zeros(len(case.buses), dtype=np.float64)
    for g, generator in enumerate(case.generators):
        bus_generators[generator.bus_index].append(g)
    for load_index, load in enumerate(case.loads):
        bus_loads[load.bus_index].append(load_index)
    for branch_index, branch in enumerate(case.branches):
        bus_flows[branch.from_bus_index].append((branch_index, -1.0))
        bus_flows[branch.to_bus_index].append((branch_index, 1.0))
    for shunt in case.fixed_shunts:
        bus_shunt[shunt.bus_index] += shunt.conductance_pu

    balance_row_starts: list[int] = []
    base_balance_rows: list[int] = []
    for state_index, state in enumerate(layout.states):
        contingency = None if state_index == 0 else case.contingencies[state_index - 1]
        rows.add((state.theta(0),), (1.0,), 0.0, 0.0)
        balance_row_starts.append(rows.num_rows)
        for bus_index in range(len(case.buses)):
            columns: list[int] = []
            coefficients: list[float] = []
            for g in bus_generators[bus_index]:
                columns.append(state.pg(g))
                coefficients.append(1.0)
            for load_index in bus_loads[bus_index]:
                columns.append(state.load(load_index))
                coefficients.append(-1.0)
            for branch_index, sign in bus_flows[bus_index]:
                columns.append(state.flow(branch_index))
                coefficients.append(sign)
            row = rows.add(columns, coefficients, bus_shunt[bus_index], bus_shunt[bus_index])
            if state_index == 0:
                base_balance_rows.append(row)

        for branch_index, branch in enumerate(case.branches):
            if contingency is not None and contingency.branch_index == branch_index:
                continue
            susceptance = 1.0 / (branch.dc_reactance_pu * branch.tap_magnitude)
            rhs = -susceptance * branch.phase_shift_rad
            rows.add(
                (
                    state.flow(branch_index),
                    state.theta(branch.from_bus_index),
                    state.theta(branch.to_bus_index),
                ),
                (1.0, -susceptance, susceptance),
                rhs,
                rhs,
            )

        for g, generator in enumerate(case.generators):
            pg = state.pg(g)
            u = state.u(g)
            startup = state.startup(g)
            shutdown = state.shutdown(g)
            rows.add((pg, u), (1.0, -generator.pmax_pu), -INF, 0.0)
            rows.add((pg, u), (-1.0, generator.pmin_pu), -INF, 0.0)
            if state_index == 0:
                rows.add(
                    (u, startup, shutdown), (1.0, -1.0, 1.0), generator.prior_on, generator.prior_on
                )
                rows.add(
                    (pg, u, startup),
                    (
                        1.0,
                        -generator.ramp_up_base_pu_per_h * case.response_base_hours,
                        -generator.pmin_pu,
                    ),
                    -INF,
                    generator.prior_p_pu,
                )
                rows.add(
                    (pg, u, shutdown),
                    (
                        -1.0,
                        -generator.ramp_down_base_pu_per_h * case.response_base_hours,
                        -generator.pmax_pu,
                    ),
                    -INF,
                    -generator.prior_p_pu,
                )
            elif contingency is not None and contingency.generator_index != g:
                rows.add(
                    (u, base.u(g), startup, shutdown),
                    (1.0, -1.0, -1.0, 1.0),
                    0.0,
                    0.0,
                )
                rows.add((startup, u), (1.0, -1.0), -INF, 0.0)
                rows.add((shutdown, u), (1.0, 1.0), -INF, 1.0)
                rows.add((base.startup(g), shutdown), (1.0, 1.0), -INF, 1.0)
                rows.add((base.shutdown(g), startup), (1.0, 1.0), -INF, 1.0)
                rows.add(
                    (pg, base.pg(g), u, startup),
                    (
                        1.0,
                        -1.0,
                        -generator.ramp_up_ctg_pu_per_h * case.response_ctg_hours,
                        -generator.pmin_pu,
                    ),
                    -INF,
                    0.0,
                )
                rows.add(
                    (base.pg(g), pg, u, shutdown),
                    (
                        1.0,
                        -1.0,
                        -generator.ramp_down_ctg_pu_per_h * case.response_ctg_hours,
                        -generator.pmax_pu,
                    ),
                    -INF,
                    0.0,
                )

        for load_index, load in enumerate(case.loads):
            value = state.load(load_index)
            if state_index == 0:
                rows.add(
                    (value,),
                    (1.0,),
                    -INF,
                    load.prior_p_pu + load.ramp_up_base_pu_per_h * case.response_base_hours,
                )
                rows.add(
                    (value,),
                    (-1.0,),
                    -INF,
                    -load.prior_p_pu + load.ramp_down_base_pu_per_h * case.response_base_hours,
                )
            else:
                rows.add(
                    (value, base.load(load_index)),
                    (1.0, -1.0),
                    -INF,
                    load.ramp_up_ctg_pu_per_h * case.response_ctg_hours,
                )
                rows.add(
                    (base.load(load_index), value),
                    (1.0, -1.0),
                    -INF,
                    load.ramp_down_ctg_pu_per_h * case.response_ctg_hours,
                )

    for g, columns in enumerate(layout.generator_segment_columns):
        rows.add((base.pg(g), *columns), (1.0, *(-1.0 for _ in columns)), 0.0, 0.0)
    for load_index, columns in enumerate(layout.load_segment_columns):
        rows.add((base.load(load_index), *columns), (1.0, *(-1.0 for _ in columns)), 0.0, 0.0)

    valid_inequality_rows: tuple[int, ...] = ()
    ablation = config.get("ablation", {})
    if bool(ablation.get("strong_valid_cuts", False)):
        valid_inequality_rows = _add_valid_inequalities(
            case,
            layout,
            rows,
            weakest_bus_count=int(ablation.get("valid_cut_bus_count", 32)),
        )

    return CanonicalModel(
        case,
        layout,
        lower,
        upper,
        primary,
        np.asarray(integer_columns, dtype=np.int32),
        rows,
        ModelMetadata(
            tuple(base_balance_rows),
            tuple(balance_row_starts),
            "base_source_cost_minus_authorized_load_benefit",
            valid_inequality_rows,
        ),
    )
