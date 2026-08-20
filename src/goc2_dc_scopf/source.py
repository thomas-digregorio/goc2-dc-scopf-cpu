from __future__ import annotations

import contextlib
import io
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import networkx as nx

from .paths import load_json, require_local_path, sha256_file

GeneratorKey = tuple[int, str]
LoadKey = tuple[int, str]
BranchKey = tuple[int, int, str]


@dataclass(frozen=True)
class CostSegment:
    width_pu: float
    marginal_per_mwh: float
    source_block: int


@dataclass(frozen=True)
class Bus:
    source_index: int
    number: int
    name: str


@dataclass(frozen=True)
class Load:
    source_index: int
    key: LoadKey
    bus_index: int
    prior_p_pu: float
    pmin_pu: float
    pmax_pu: float
    ramp_up_base_pu_per_h: float
    ramp_down_base_pu_per_h: float
    ramp_up_ctg_pu_per_h: float
    ramp_down_ctg_pu_per_h: float
    benefit_segments: tuple[CostSegment, ...]


@dataclass(frozen=True)
class Generator:
    source_index: int
    key: GeneratorKey
    bus_index: int
    prior_on: int
    prior_p_pu: float
    pmin_pu: float
    pmax_pu: float
    ramp_up_base_pu_per_h: float
    ramp_down_base_pu_per_h: float
    ramp_up_ctg_pu_per_h: float
    ramp_down_ctg_pu_per_h: float
    startup_qualified_base: int
    shutdown_qualified_base: int
    startup_qualified_ctg: int
    shutdown_qualified_ctg: int
    on_cost_per_h: float
    startup_cost: float
    shutdown_cost: float
    cost_segments: tuple[CostSegment, ...]


@dataclass(frozen=True)
class Branch:
    source_index: int
    key: BranchKey
    kind: Literal["line", "transformer"]
    from_bus_index: int
    to_bus_index: int
    reactance_pu: float
    tap_magnitude: float
    phase_shift_rad: float
    normal_limit_pu: float
    emergency_limit_pu: float


@dataclass(frozen=True)
class FixedShunt:
    source_index: int
    key: tuple[int, str]
    bus_index: int
    conductance_pu: float


@dataclass(frozen=True)
class Contingency:
    source_index: int
    label: str
    kind: Literal["branch", "generator"]
    branch_index: int | None
    generator_index: int | None
    source_events: tuple[str, ...]


@dataclass(frozen=True)
class CaseData:
    profile: str
    scenario: str
    base_mva: float
    delta_hours: float
    response_base_hours: float
    response_ctg_hours: float
    buses: tuple[Bus, ...]
    loads: tuple[Load, ...]
    generators: tuple[Generator, ...]
    branches: tuple[Branch, ...]
    fixed_shunts: tuple[FixedShunt, ...]
    contingencies: tuple[Contingency, ...]
    source_hashes: dict[str, str]
    source_directory: str
    parser_commit: str
    untranslated: tuple[dict[str, Any], ...]

    @property
    def states(self) -> int:
        return 1 + len(self.contingencies)


def _install_parser_path(root: Path) -> None:
    vendor = require_local_path(root / "vendor" / "C2DataUtilities", "parser dependency")
    if not vendor.is_dir():
        raise FileNotFoundError(
            f"Missing parser submodule at {vendor}; run git submodule update --init --recursive"
        )
    value = str(vendor)
    if value not in sys.path:
        sys.path.insert(0, value)


def _capped_segments(
    blocks: list[dict[str, Any]], maximum_mw: float, base_mva: float, *, benefit: bool
) -> tuple[CostSegment, ...]:
    if maximum_mw < -1e-9:
        raise ValueError(f"Negative cost-domain maximum: {maximum_mw}")
    previous: float | None = None
    remaining = max(0.0, maximum_mw)
    result: list[CostSegment] = []
    for block_index, block in enumerate(blocks):
        width = float(block["pmax"])
        marginal = float(block["c"])
        if width < 0.0 or not math.isfinite(width) or not math.isfinite(marginal):
            raise ValueError(f"Invalid source cost block {block_index}: {block}")
        if previous is not None:
            if benefit and marginal > previous + 1e-9:
                raise ValueError("Load benefit blocks are not concave in source order")
            if not benefit and marginal < previous - 1e-9:
                raise ValueError("Generator cost blocks are not convex in source order")
        previous = marginal
        used = min(width, remaining)
        if used > 1e-12:
            result.append(CostSegment(used / base_mva, marginal, block_index))
            remaining -= used
        if remaining <= 1e-9:
            break
    if remaining > 1e-6:
        raise ValueError(f"Source blocks leave {remaining:.9g} MW of the domain uncovered")
    return tuple(result)


def _verify_source_files(source_directory: Path, manifest: dict[str, Any]) -> dict[str, str]:
    expected = manifest["scenario"]["files"]
    observed: dict[str, str] = {}
    for filename, record in expected.items():
        path = require_local_path(source_directory / filename, "immutable source input")
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        if actual.casefold() != str(record["sha256"]).casefold():
            raise ValueError(f"SHA256 mismatch for {path}: expected {record['sha256']}, got {actual}")
        if path.stat().st_size != int(record["bytes"]):
            raise ValueError(f"Byte-size mismatch for {path}")
        observed[filename] = actual
    return observed


def read_case(root: Path, config: dict[str, Any]) -> CaseData:
    root = require_local_path(root, "repository")
    source_directory = require_local_path(root / config["source_directory"], "source")
    manifest_path = require_local_path(root / config["source_manifest"], "source manifest")
    manifest = load_json(manifest_path)
    hashes = _verify_source_files(source_directory, manifest)
    _install_parser_path(root)
    from data_utilities.data import Data  # type: ignore[import-not-found]

    parsed = Data()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        parsed.read(
            str(source_directory / "case.raw"),
            str(source_directory / "case.json"),
            str(source_directory / "case.con"),
        )

    raw = parsed.raw
    supplemental = parsed.sup
    base_mva = float(raw.case_identification.sbase)
    if base_mva <= 0.0:
        raise ValueError("Source base MVA must be positive")

    raw_buses = list(raw.buses.values())
    bus_map = {record.i: index for index, record in enumerate(raw_buses)}
    buses = tuple(Bus(i, int(record.i), str(record.name).strip()) for i, record in enumerate(raw_buses))

    loads: list[Load] = []
    for source_index, record in enumerate(raw.loads.values()):
        if int(record.status) != 1:
            continue
        key = (int(record.i), str(record.id).strip())
        source = supplemental.loads[key]
        prior_mw = float(record.pl)
        lower_mw = prior_mw * float(source["tmin"])
        upper_mw = prior_mw * float(source["tmax"])
        if lower_mw > upper_mw + 1e-9:
            raise ValueError(f"Invalid load bounds for {key}")
        loads.append(
            Load(
                source_index,
                key,
                bus_map[key[0]],
                prior_mw / base_mva,
                lower_mw / base_mva,
                upper_mw / base_mva,
                float(source["prumax"]) / base_mva,
                float(source["prdmax"]) / base_mva,
                float(source["prumaxctg"]) / base_mva,
                float(source["prdmaxctg"]) / base_mva,
                _capped_segments(source["cblocks"], upper_mw, base_mva, benefit=True),
            )
        )

    generators: list[Generator] = []
    for source_index, record in enumerate(raw.generators.values()):
        key = (int(record.i), str(record.id).strip())
        source = supplemental.generators[key]
        generators.append(
            Generator(
                source_index,
                key,
                bus_map[key[0]],
                int(record.stat),
                float(record.pg) / base_mva,
                float(record.pb) / base_mva,
                float(record.pt) / base_mva,
                float(source["prumax"]) / base_mva,
                float(source["prdmax"]) / base_mva,
                float(source["prumaxctg"]) / base_mva,
                float(source["prdmaxctg"]) / base_mva,
                int(source["suqual"]),
                int(source["sdqual"]),
                int(source["suqualctg"]),
                int(source["sdqualctg"]),
                float(source["oncost"]),
                float(source["sucost"]),
                float(source["sdcost"]),
                _capped_segments(source["cblocks"], float(record.pt), base_mva, benefit=False),
            )
        )

    branches: list[Branch] = []
    branch_map: dict[BranchKey, int] = {}
    for source_index, record in enumerate(raw.nontransformer_branches.values()):
        if int(record.st) != 1:
            continue
        key = (int(record.i), int(record.j), str(record.ckt).strip())
        if abs(float(record.x)) <= 1e-12:
            raise ValueError(f"Zero line reactance for {key}")
        branch_map[key] = len(branches)
        branches.append(
            Branch(
                source_index,
                key,
                "line",
                bus_map[key[0]],
                bus_map[key[1]],
                float(record.x),
                1.0,
                0.0,
                float(record.ratea) / base_mva,
                float(record.ratec) / base_mva,
            )
        )
    transformer_offset = len(raw.nontransformer_branches)
    for source_index, record in enumerate(raw.transformers.values(), transformer_offset):
        if int(record.stat) != 1:
            continue
        key = (int(record.i), int(record.j), str(record.ckt).strip())
        if key in branch_map:
            raise ValueError(f"Ambiguous line/transformer identity {key}")
        if int(record.cw) != 1 or int(record.cz) != 1:
            raise ValueError(f"Unsupported noncanonical transformer CW/CZ for {key}")
        if abs(float(record.x12)) <= 1e-12:
            raise ValueError(f"Zero transformer reactance for {key}")
        tap = float(record.windv1) / float(record.windv2)
        if tap <= 0.0:
            raise ValueError(f"Nonpositive transformer tap for {key}")
        branch_map[key] = len(branches)
        branches.append(
            Branch(
                source_index,
                key,
                "transformer",
                bus_map[key[0]],
                bus_map[key[1]],
                float(record.x12),
                tap,
                math.radians(float(record.ang1)),
                float(record.rata1) / base_mva,
                float(record.ratc1) / base_mva,
            )
        )

    fixed_shunts: list[FixedShunt] = []
    for source_index, record in enumerate(raw.fixed_shunts.values()):
        if int(record.status) != 1:
            continue
        key = (int(record.i), str(record.id).strip())
        fixed_shunts.append(
            FixedShunt(source_index, key, bus_map[key[0]], float(record.gl) / base_mva)
        )

    generator_map = {record.key: index for index, record in enumerate(generators)}
    contingencies: list[Contingency] = []
    untranslated: list[dict[str, Any]] = []
    for source_index, record in enumerate(parsed.con.contingencies.values()):
        branch_events = list(record.branch_out_events)
        generator_events = list(record.generator_out_events)
        event_count = len(branch_events) + len(generator_events)
        if event_count != 1:
            untranslated.append(
                {"label": record.label, "reason": f"expected one source event, found {event_count}"}
            )
            continue
        if branch_events:
            event = branch_events[0]
            key = (int(event.i), int(event.j), str(event.ckt).strip())
            if key not in branch_map:
                untranslated.append({"label": record.label, "reason": f"branch not active: {key}"})
                continue
            contingencies.append(
                Contingency(source_index, str(record.label), "branch", branch_map[key], None, (str(key),))
            )
        else:
            event = generator_events[0]
            key = (int(event.i), str(event.id).strip())
            if key not in generator_map:
                untranslated.append({"label": record.label, "reason": f"generator absent: {key}"})
                continue
            contingencies.append(
                Contingency(
                    source_index, str(record.label), "generator", None, generator_map[key], (str(key),)
                )
            )

    if untranslated:
        details = "; ".join(f"{x['label']}: {x['reason']}" for x in untranslated[:10])
        raise ValueError(f"Untranslated source contingencies are not allowed in v1: {details}")

    graph = nx.MultiGraph()
    graph.add_nodes_from(range(len(buses)))
    for index, branch in enumerate(branches):
        graph.add_edge(branch.from_bus_index, branch.to_bus_index, key=index)
    if not nx.is_connected(graph):
        raise ValueError("Base network is disconnected")
    for contingency in contingencies:
        if contingency.branch_index is None:
            continue
        branch = branches[contingency.branch_index]
        copy = graph.copy()
        copy.remove_edge(branch.from_bus_index, branch.to_bus_index, contingency.branch_index)
        if not nx.is_connected(copy):
            raise ValueError(f"Source contingency {contingency.label} islands the DC network")

    system = supplemental.sup_jsonobj["systemparameters"]
    return CaseData(
        str(config["profile"]),
        str(config["scenario"]),
        base_mva,
        float(system["delta"]),
        float(system["deltar"]),
        float(system["deltarctg"]),
        buses,
        tuple(loads),
        tuple(generators),
        tuple(branches),
        tuple(fixed_shunts),
        tuple(contingencies),
        hashes,
        str(source_directory),
        str(manifest["parser"]["commit"]),
        tuple(untranslated),
    )


def audit_case(case: CaseData) -> dict[str, Any]:
    return {
        "profile": case.profile,
        "scenario": case.scenario,
        "source_directory": case.source_directory,
        "source_hashes": case.source_hashes,
        "parser_commit": case.parser_commit,
        "base_mva": case.base_mva,
        "interval_hours": case.delta_hours,
        "response_base_hours": case.response_base_hours,
        "response_contingency_hours": case.response_ctg_hours,
        "counts": {
            "buses": len(case.buses),
            "loads": len(case.loads),
            "generators": len(case.generators),
            "prior_online_generators": sum(g.prior_on for g in case.generators),
            "branches": len(case.branches),
            "line_contingencies": sum(c.kind == "branch" for c in case.contingencies),
            "generator_contingencies": sum(c.kind == "generator" for c in case.contingencies),
            "contingencies": len(case.contingencies),
            "states": case.states,
        },
        "source_permissions": {
            "base_startup": sum(g.startup_qualified_base for g in case.generators),
            "base_shutdown": sum(g.shutdown_qualified_base for g in case.generators),
            "contingency_startup": sum(g.startup_qualified_ctg for g in case.generators),
            "contingency_shutdown": sum(g.shutdown_qualified_ctg for g in case.generators),
        },
        "network": {
            "nonunit_taps": sum(abs(b.tap_magnitude - 1.0) > 1e-12 for b in case.branches),
            "nonzero_phase_shifts": sum(abs(b.phase_shift_rad) > 1e-12 for b in case.branches),
            "emergency_limit_differs": sum(
                abs(b.emergency_limit_pu - b.normal_limit_pu) > 1e-12 for b in case.branches
            ),
            "active_shunts": sum(abs(s.conductance_pu) > 1e-12 for s in case.fixed_shunts),
        },
        "untranslated": list(case.untranslated),
    }

