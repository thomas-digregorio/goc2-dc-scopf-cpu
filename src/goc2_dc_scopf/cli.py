from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from jsonschema import Draft202012Validator

from .benchmark import repair_inverted_price_sign, resume_saved_primary, run_official_benchmark
from .checker import verify_primary_checkpoint, verify_result
from .highs import validate_model_translation
from .model import build_extensive_model, estimate_extensive_size
from .paths import configure_local_runtime, load_json, repo_root, require_local_path, resolve_from
from .source import audit_case, read_case

DEFAULT_CONFIG = "configs/GOC2-DC-D1-CORRECTIVE-v2-617.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="goc2-dc-scopf")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="JSON configuration path")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("ingest", help="hash, parse, and audit the immutable source scenario")
    preflight = subparsers.add_parser(
        "preflight", help="estimate or build the extensive model without solving"
    )
    preflight.add_argument(
        "--build", action="store_true", help="construct the complete sparse matrix"
    )
    preflight.add_argument(
        "--pass-highs",
        action="store_true",
        help="pass the constructed model to HiGHS without solving",
    )
    subparsers.add_parser("benchmark", help="perform one cold official benchmark run")
    subparsers.add_parser(
        "resume",
        help="resume verification and pricing from a retained primary without rerunning the MILP",
    )
    subparsers.add_parser(
        "repair-price-sign",
        help="repair the one known v2 price-sign defect without rerunning an optimizer",
    )
    verify_primary = subparsers.add_parser(
        "verify-primary", help="independently reverify a saved primary checkpoint"
    )
    verify_primary.add_argument("checkpoint", help="primary-checkpoint.json path")
    verify = subparsers.add_parser("verify", help="independently reverify an existing result")
    verify.add_argument("result", help="result.json path")
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    root = repo_root()
    configure_local_runtime(root)
    config_path = resolve_from(root, args.config, "configuration")
    config = load_json(config_path)
    schema = load_json(resolve_from(root, "schemas/config.schema.json", "configuration schema"))
    Draft202012Validator(schema).validate(config)
    if args.command == "ingest":
        print(json.dumps(audit_case(read_case(root, config)), indent=2))
        return
    if args.command == "preflight":
        case = read_case(root, config)
        report: dict[str, object] = {"estimate": estimate_extensive_size(case)}
        if args.build or args.pass_highs:
            started = time.perf_counter()
            model = build_extensive_model(case, config)
            report["actual"] = model.statistics()
            report["build_seconds"] = time.perf_counter() - started
            if args.pass_highs:
                started = time.perf_counter()
                report["highs_translation"] = validate_model_translation(model)
                report["highs_translation_seconds"] = time.perf_counter() - started
        print(json.dumps(report, indent=2))
        return
    if args.command == "benchmark":
        payload = run_official_benchmark(root, config_path, config)
        print(
            json.dumps(
                {"official_run": payload["official_run"], "checker": payload["checker"]}, indent=2
            )
        )
        return
    if args.command == "resume":
        payload = resume_saved_primary(root, config_path, config)
        print(
            json.dumps(
                {"official_run": payload["official_run"], "checker": payload["checker"]},
                indent=2,
            )
        )
        return
    if args.command == "repair-price-sign":
        payload = repair_inverted_price_sign(root, config_path, config)
        print(json.dumps({"pricing": payload["pricing"], "checker": payload["checker"]}, indent=2))
        return
    if args.command == "verify-primary":
        checkpoint = require_local_path(Path(args.checkpoint), "primary checkpoint")
        print(
            json.dumps(verify_primary_checkpoint(root, config, checkpoint, config_path), indent=2)
        )
        return
    if args.command == "verify":
        result = require_local_path(Path(args.result), "result JSON")
        print(json.dumps(verify_result(root, config, result, config_path), indent=2))
        return
    raise AssertionError(args.command)


if __name__ == "__main__":
    main()
