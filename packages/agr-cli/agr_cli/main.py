"""AGR CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from agr import AGRClient, AGRError


def _build_common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--api-key", default=None, help="AGR API key. Falls back to AGR_API_KEY.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AGR_BASE_URL", "https://api.agr.dev"),
        help="AGR API base URL. Falls back to AGR_BASE_URL.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of friendly text.",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    common = _build_common_parser()
    parser = argparse.ArgumentParser(prog="agr", description="AGR platform command line interface.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    eval_parser = subparsers.add_parser(
        "eval",
        parents=[common],
        help="Evaluate an action against AGR policies.",
    )
    _add_request_arguments(eval_parser)
    eval_parser.set_defaults(handler=_handle_eval)

    simulate_parser = subparsers.add_parser(
        "simulate",
        parents=[common],
        help="Simulate an AGR policy decision without side effects.",
    )
    _add_request_arguments(simulate_parser)
    simulate_parser.set_defaults(handler=_handle_simulate)

    policy_parser = subparsers.add_parser("policy", help="Manage AGR policies.")
    policy_subparsers = policy_parser.add_subparsers(dest="policy_command", required=True)
    apply_parser = policy_subparsers.add_parser(
        "apply",
        parents=[common],
        help="Import one or more policies from a Cedar, JSON, or YAML file.",
    )
    apply_parser.add_argument("--file", required=True, help="Path to a Cedar, JSON, or YAML file.")
    apply_parser.add_argument(
        "--name",
        default=None,
        help="Policy name for raw .cedar files. Defaults to the file stem.",
    )
    apply_parser.add_argument(
        "--level",
        choices=("org", "project", "agent"),
        default="org",
        help="Policy scope for raw .cedar files.",
    )
    apply_parser.add_argument(
        "--state",
        choices=("draft", "active", "archived"),
        default="active",
        help="Policy state for raw .cedar files.",
    )
    apply_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing policies that share the same name.",
    )
    apply_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the import without persisting anything.",
    )
    apply_parser.set_defaults(handler=_handle_policy_apply)

    return parser


def _add_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", required=True, help="Agent identifier.")
    parser.add_argument("--action", required=True, help="Action name.")
    parser.add_argument("--resource", required=True, help="Resource identifier.")
    parser.add_argument(
        "--context",
        default="{}",
        help="JSON object of context values. Defaults to {}.",
    )


def _make_client(args: argparse.Namespace) -> AGRClient:
    return AGRClient(api_key=args.api_key, base_url=args.base_url)


def _parse_context(context_text: str) -> dict[str, object]:
    try:
        payload = json.loads(context_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid context JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Context must be a JSON object.")
    return payload


def _handle_eval(args: argparse.Namespace) -> Any:
    client = _make_client(args)
    try:
        return client.evaluate(
            agent=args.agent,
            action=args.action,
            resource=args.resource,
            context=_parse_context(args.context),
        )
    finally:
        client.close()


def _handle_simulate(args: argparse.Namespace) -> Any:
    client = _make_client(args)
    try:
        return client.simulate(
            agent=args.agent,
            action=args.action,
            resource=args.resource,
            context=_parse_context(args.context),
        )
    finally:
        client.close()


def _load_yaml(path: Path) -> object:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError(
            "YAML parsing is unavailable. Install PyYAML or use JSON/Cedar input instead."
        ) from exc

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _normalize_policy_payload(path: Path, args: argparse.Namespace) -> list[dict[str, object]]:
    suffix = path.suffix.lower()

    if suffix == ".cedar":
        rule = path.read_text(encoding="utf-8").strip()
        if not rule:
            raise ValueError(f"Policy file '{path}' is empty.")
        return [
            {
                "name": args.name or path.stem,
                "level": args.level,
                "cedar_rule": rule,
                "state": args.state,
                "active": args.state == "active",
            }
        ]

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        payload = _load_yaml(path)
    else:
        raise ValueError("Unsupported policy file type. Use .cedar, .json, .yaml, or .yml.")

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        policies = payload.get("policies")
        if isinstance(policies, list):
            return policies
        if "cedar_rule" in payload:
            return [payload]
    raise ValueError("Policy input must be a policy object, a list, or an object with 'policies'.")


def _handle_policy_apply(args: argparse.Namespace) -> dict[str, object]:
    path = Path(args.file).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Policy file not found: {path}")

    policies = _normalize_policy_payload(path, args)
    client = _make_client(args)
    try:
        return client.import_policies(
            policies=policies,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
    finally:
        client.close()


def _print_json(data: Any) -> None:
    payload = asdict(data) if is_dataclass(data) else data
    print(json.dumps(payload, indent=2, sort_keys=True))


def _print_result(data: Any, json_output: bool) -> None:
    if json_output:
        _print_json(data)
        return

    if is_dataclass(data):
        payload = asdict(data)
        _print_key_values(payload)
        return

    if isinstance(data, dict) and "results" in data:
        _print_import_summary(data)
        return

    _print_json(data)


def _print_key_values(payload: dict[str, Any]) -> None:
    rows: list[tuple[str, Any]] = []
    for key, value in payload.items():
        if value is None:
            continue
        label = key.replace("_", " ").title()
        rows.append((label, value))

    width = max(len(label) for label, _ in rows) if rows else 0
    for label, value in rows:
        if isinstance(value, dict):
            value = json.dumps(value, sort_keys=True)
        elif isinstance(value, list):
            value = json.dumps(value)
        print(f"{label.ljust(width)} : {value}")


def _print_import_summary(payload: dict[str, Any]) -> None:
    summary_keys = ("dry_run", "total", "created", "updated", "skipped", "errors")
    summary = {key: payload.get(key) for key in summary_keys}
    _print_key_values(summary)
    print("")
    for result in payload.get("results", []):
        name = result.get("name", "<unknown>")
        status = result.get("status", "unknown")
        error = result.get("error")
        suffix = f" ({error})" if error else ""
        print(f"- {name}: {status}{suffix}")


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = args.handler(args)
    except (AGRError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_result(result, args.json_output)
    return 0
