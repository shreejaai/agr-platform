#!/usr/bin/env python3
"""AGR policy validation script for the GitHub Action.

Supports:
  - validating Cedar/JSON/YAML policy files
  - checking only changed policies in a pull request
  - running local evaluation scenarios against the repo policy corpus
  - failing CI on conflicts or behavior regressions
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import httpx
    import yaml
except ImportError:
    print("::error::Missing dependencies. Run: pip install httpx pyyaml")
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parents[2]
AGR_CORE_PATH = REPO_ROOT / "packages" / "agr-core"
if str(AGR_CORE_PATH) not in sys.path:
    sys.path.insert(0, str(AGR_CORE_PATH))

SUPPORTED_SUFFIXES = {".cedar", ".json", ".yaml", ".yml"}
VALID_DECISIONS = {"ALLOW", "DENY", "APPROVAL_REQUIRED"}
VALID_STARTS = ("permit", "forbid")


@dataclass
class EvaluationCase:
    name: str
    action: str
    resource: str
    expect: str
    agent: str
    context: dict[str, object] = field(default_factory=dict)


@dataclass
class PolicyFileEntry:
    file: Path
    name: str
    cedar_rule: str
    level: str = "org"


@dataclass
class ValidatorConfig:
    api_key: str
    api_base_url: str
    policy_dir: Path
    config_file: Path | None
    dry_run_agent: str
    fail_on_conflict: bool
    fail_on_violation: bool
    changed_only: bool
    evaluation_tests: list[EvaluationCase] = field(default_factory=list)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() == "true"


def _gh_annotation(level: str, message: str, file: str | None = None) -> None:
    if file:
        print(f"::{level} file={file}::{message}")
    else:
        print(f"::{level}::{message}")


def _notice(message: str) -> None:
    print(f"::notice::{message}")


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def load_config() -> ValidatorConfig:
    config_path_raw = os.environ.get("CONFIG_FILE", ".agr-policy-check.yml").strip()
    config_path = REPO_ROOT / config_path_raw if config_path_raw else None

    config = ValidatorConfig(
        api_key=os.environ.get("AGR_API_KEY", ""),
        api_base_url=os.environ.get("AGR_BASE_URL", "https://api.agr.dev").rstrip("/"),
        policy_dir=(REPO_ROOT / os.environ.get("POLICY_DIR", ".")).resolve(),
        config_file=config_path.resolve() if config_path is not None else None,
        dry_run_agent=os.environ.get("DRY_RUN_AGENT", "").strip(),
        fail_on_conflict=_env_flag("FAIL_ON_CONFLICT", True),
        fail_on_violation=_env_flag("FAIL_ON_VIOLATION", True),
        changed_only=_env_flag("CHANGED_ONLY", False),
    )

    if config.config_file and config.config_file.exists():
        raw = yaml.safe_load(config.config_file.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("YAML config must be a mapping/object.")

        policy_dir = raw.get("policy_dir")
        if isinstance(policy_dir, str) and policy_dir.strip():
            config.policy_dir = (REPO_ROOT / policy_dir).resolve()

        for field_name in ("fail_on_conflict", "fail_on_violation", "changed_only"):
            value = raw.get(field_name)
            if isinstance(value, bool):
                setattr(config, field_name, value)

        tests = raw.get("evaluation_tests", [])
        if tests is not None and not isinstance(tests, list):
            raise ValueError("evaluation_tests must be a list.")
        for index, item in enumerate(tests or [], start=1):
            if not isinstance(item, dict):
                raise ValueError(f"evaluation_tests[{index}] must be an object.")
            expect = str(item.get("expect", "")).upper()
            if expect not in VALID_DECISIONS:
                raise ValueError(
                    f"evaluation_tests[{index}].expect must be one of {sorted(VALID_DECISIONS)}."
                )
            agent = str(item.get("agent") or config.dry_run_agent or "").strip()
            if not agent:
                raise ValueError(
                    f"evaluation_tests[{index}] is missing agent, and DRY_RUN_AGENT is not set."
                )
            context = item.get("context") or {}
            if not isinstance(context, dict):
                raise ValueError(f"evaluation_tests[{index}].context must be an object.")
            config.evaluation_tests.append(
                EvaluationCase(
                    name=str(item.get("name") or f"evaluation-{index}"),
                    agent=agent,
                    action=str(item["action"]),
                    resource=str(item["resource"]),
                    expect=expect,
                    context=context,
                )
            )

    return config


def discover_policy_files(policy_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in policy_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _load_structured_policy_file(path: Path) -> object:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_policy_entries(path: Path) -> list[PolicyFileEntry]:
    if path.suffix.lower() == ".cedar":
        rule = path.read_text(encoding="utf-8").strip()
        if not rule:
            raise ValueError("Cedar file is empty.")
        return [PolicyFileEntry(file=path, name=path.stem, cedar_rule=rule)]

    payload = _load_structured_policy_file(path)
    if isinstance(payload, dict):
        candidate = payload.get("policies")
        if isinstance(candidate, list):
            entries = candidate
        elif "cedar_rule" in payload:
            entries = [payload]
        else:
            raise ValueError("Structured policy file must contain 'policies' or 'cedar_rule'.")
    elif isinstance(payload, list):
        entries = payload
    else:
        raise ValueError("Structured policy file must decode to an object or list.")

    loaded: list[PolicyFileEntry] = []
    for index, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Policy #{index} in {_relative(path)} must be an object.")
        rule = item.get("cedar_rule")
        if not isinstance(rule, str) or not rule.strip():
            raise ValueError(f"Policy #{index} in {_relative(path)} is missing 'cedar_rule'.")
        name = item.get("name")
        loaded.append(
            PolicyFileEntry(
                file=path,
                name=str(name)
                if isinstance(name, str) and name.strip()
                else f"{path.stem}-{index}",
                cedar_rule=rule.strip(),
                level=str(item.get("level", "org")),
            )
        )
    return loaded


def load_policy_corpus(files: list[Path]) -> tuple[list[PolicyFileEntry], list[dict[str, str]]]:
    policies: list[PolicyFileEntry] = []
    errors: list[dict[str, str]] = []
    for path in files:
        try:
            policies.extend(load_policy_entries(path))
        except Exception as exc:
            errors.append({"file": _relative(path), "error": str(exc)})
    return policies, errors


def _validate_syntax(rule: str) -> list[str]:
    errors: list[str] = []
    lower = rule.lower()
    if not any(lower.startswith(prefix) for prefix in VALID_STARTS):
        errors.append("Rule must start with 'permit' or 'forbid'.")
    if not rule.rstrip().endswith(";"):
        errors.append("Rule must end with ';'.")

    depth = 0
    for ch in rule:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            errors.append("Unmatched closing parenthesis.")
            break
    if depth != 0:
        errors.append("Unclosed parenthesis.")
    return errors


def api_validate(
    client: httpx.Client, config: ValidatorConfig, policy: PolicyFileEntry
) -> dict[str, Any]:
    try:
        response = client.post(
            f"{config.api_base_url}/v1/policies",
            json={
                "name": policy.name,
                "cedar_rule": policy.cedar_rule,
                "level": policy.level,
                "state": "draft",
                "description": f"CI validation for {_relative(policy.file)}",
            },
        )
    except httpx.RequestError as exc:
        return {"valid": False, "error": f"API request failed: {exc}", "conflicts": []}

    if response.status_code == 201:
        data = response.json()
        policy_id = data.get("id")
        if isinstance(policy_id, str):
            client.delete(f"{config.api_base_url}/v1/policies/{policy_id}")
        conflicts = data.get("conflicts")
        if not isinstance(conflicts, list):
            conflicts = []
        return {"valid": True, "conflicts": [str(item) for item in conflicts]}

    if response.status_code == 422:
        detail = response.json().get("detail", "Validation failed.")
        if isinstance(detail, list):
            detail = "; ".join(str(item.get("msg", item)) for item in detail)
        return {"valid": False, "error": str(detail), "conflicts": []}

    return {
        "valid": False,
        "error": f"API returned HTTP {response.status_code}: {response.text}",
        "conflicts": [],
    }


def _load_changed_files() -> list[str] | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    base_sha: str | None = None
    head_sha = os.environ.get("GITHUB_SHA", "HEAD")

    if event_path and Path(event_path).exists():
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        pull_request = payload.get("pull_request")
        if isinstance(pull_request, dict):
            base = pull_request.get("base")
            head = pull_request.get("head")
            if isinstance(base, dict) and isinstance(base.get("sha"), str):
                base_sha = str(base["sha"])
            if isinstance(head, dict) and isinstance(head.get("sha"), str):
                head_sha = str(head["sha"])

    if not base_sha:
        return None

    proc = subprocess.run(
        ["git", "diff", "--name-only", base_sha, head_sha],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        _notice("Could not determine changed files from git diff; validating all policy files.")
        return None
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def select_validation_files(all_files: list[Path], changed_files: list[str] | None) -> list[Path]:
    if not changed_files:
        return all_files
    changed_paths = {(REPO_ROOT / item).resolve() for item in changed_files}
    return [path for path in all_files if path.resolve() in changed_paths]


def run_evaluation_tests(
    policies: list[PolicyFileEntry], cases: list[EvaluationCase]
) -> list[dict[str, Any]]:
    from policy_engine import evaluate_policies

    corpus = [
        {"id": f"{_relative(policy.file)}::{index}", "cedar_rule": policy.cedar_rule}
        for index, policy in enumerate(policies, start=1)
    ]

    results: list[dict[str, Any]] = []
    for case in cases:
        evaluation = evaluate_policies(
            cedar_policies=corpus,
            agent_id=case.agent,
            action=case.action,
            resource=case.resource,
            context=case.context,
        )
        passed = evaluation.decision == case.expect
        results.append(
            {
                "name": case.name,
                "agent": case.agent,
                "action": case.action,
                "resource": case.resource,
                "expected": case.expect,
                "actual": evaluation.decision,
                "passed": passed,
                "reason": evaluation.reason,
                "policy_source": evaluation.policy_source,
                "fallback_used": evaluation.fallback_used,
                "fallback_reason": evaluation.fallback_reason,
            }
        )
    return results


def write_output(summary: dict[str, Any]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"validation-result={json.dumps(summary, sort_keys=True)}\n")


def main() -> int:
    try:
        config = load_config()
    except Exception as exc:
        _gh_annotation("error", f"Invalid GitHub Action config: {exc}")
        return 1

    if not config.api_key:
        _gh_annotation("error", "AGR_API_KEY is not set. Add it as a GitHub secret.")
        return 1

    all_files = discover_policy_files(config.policy_dir)
    if not all_files:
        _notice(
            f"No policy files found under '{_relative(config.policy_dir)}'. Nothing to validate."
        )
        summary = {
            "policy_dir": _relative(config.policy_dir),
            "total_policy_files": 0,
            "validated_files": 0,
            "errors": 0,
            "evaluation_failures": 0,
            "changed_only": config.changed_only,
            "results": [],
            "evaluation_tests": [],
        }
        write_output(summary)
        return 0

    changed_files = _load_changed_files() if config.changed_only else None
    validation_files = select_validation_files(all_files, changed_files)
    if config.changed_only and not validation_files:
        _notice("No changed policy files detected in this pull request. Skipping validation.")
        summary = {
            "policy_dir": _relative(config.policy_dir),
            "total_policy_files": len(all_files),
            "validated_files": 0,
            "errors": 0,
            "evaluation_failures": 0,
            "changed_only": True,
            "results": [],
            "evaluation_tests": [],
        }
        write_output(summary)
        return 0

    print(
        f"Found {len(all_files)} policy file(s); validating {len(validation_files)} file(s)"
        f"{' changed in this PR' if config.changed_only else ''}."
    )

    loaded_all, corpus_errors = load_policy_corpus(all_files)
    errors_total = 0
    results: list[dict[str, Any]] = []

    for issue in corpus_errors:
        _gh_annotation("error", issue["error"], file=issue["file"])
        errors_total += 1
        results.append({"file": issue["file"], "valid": False, "errors": [issue["error"]]})

    policies_by_file: dict[Path, list[PolicyFileEntry]] = {}
    for policy in loaded_all:
        policies_by_file.setdefault(policy.file, []).append(policy)

    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    with httpx.Client(headers=headers, timeout=30.0) as client:
        for path in validation_files:
            rel = _relative(path)
            loaded_entries = policies_by_file.get(path)
            if not loaded_entries:
                continue

            file_errors: list[str] = []
            file_conflicts: list[str] = []
            print(f"  Validating: {rel}")

            for policy in loaded_entries:
                syntax_errors = _validate_syntax(policy.cedar_rule)
                for error in syntax_errors:
                    _gh_annotation("error", f"{policy.name}: {error}", file=rel)
                file_errors.extend(f"{policy.name}: {error}" for error in syntax_errors)
                if syntax_errors:
                    continue

                api_result = api_validate(client, config, policy)
                if not api_result["valid"]:
                    error = str(api_result.get("error", "Unknown error"))
                    _gh_annotation("error", f"{policy.name}: {error}", file=rel)
                    file_errors.append(f"{policy.name}: {error}")
                    continue

                conflicts = api_result.get("conflicts", [])
                if conflicts:
                    for conflict in conflicts:
                        level = "error" if config.fail_on_conflict else "warning"
                        _gh_annotation(level, f"{policy.name}: {conflict}", file=rel)
                    file_conflicts.extend(str(conflict) for conflict in conflicts)

            errors_total += len(file_errors)
            if config.fail_on_conflict:
                errors_total += len(file_conflicts)

            results.append(
                {
                    "file": rel,
                    "valid": not file_errors,
                    "errors": file_errors,
                    "conflicts": file_conflicts,
                }
            )

    evaluation_results: list[dict[str, Any]] = []
    evaluation_failures = 0
    if config.evaluation_tests:
        evaluation_results = run_evaluation_tests(loaded_all, config.evaluation_tests)
        for item in evaluation_results:
            if item["passed"]:
                continue
            message = (
                f"{item['name']}: expected {item['expected']} but got {item['actual']} "
                f"for {item['action']} on {item['resource']}"
            )
            level = "error" if config.fail_on_violation else "warning"
            _gh_annotation(level, message)
            evaluation_failures += 1
        if config.fail_on_violation:
            errors_total += evaluation_failures

    summary = {
        "policy_dir": _relative(config.policy_dir),
        "total_policy_files": len(all_files),
        "validated_files": len(validation_files),
        "errors": errors_total,
        "evaluation_failures": evaluation_failures,
        "changed_only": config.changed_only,
        "results": results,
        "evaluation_tests": evaluation_results,
    }
    write_output(summary)

    if errors_total > 0:
        _gh_annotation("error", f"Validation failed with {errors_total} error(s).")
        return 1

    print("All policy checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
