"""Cedar policy evaluation engine.

Primary: cedar-policy CLI via subprocess (if `cedar` binary is on PATH).
Fallback: Python regex evaluator for dev/CI without cedar CLI installed.

Decision values: "ALLOW" | "DENY" | "APPROVAL_REQUIRED"

APPROVAL_REQUIRED detection (both paths):
  A `forbid ... unless { context.approval_status == "approved" }` pattern means the
  action requires human sign-off. Detected by:
    1. First eval with given context → DENY
    2. Re-eval with approval_status="approved" injected → if ALLOW, return APPROVAL_REQUIRED
"""

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)
DEFAULT_CEDAR_POOL_SIZE = 4
CEDAR_DEGRADED = False
_CEDAR_POOL_SIZE_OVERRIDE: int | None = None
_cedar_pool: "CedarProcessPool | None" = None
_cedar_pool_lock = threading.Lock()


@dataclass
class ValidationResult:
    valid: bool
    error: str | None = None


@dataclass
class EvaluationResult:
    decision: str  # "ALLOW" | "DENY" | "APPROVAL_REQUIRED"
    reason: str
    policy_id: str | None
    requires_approval: bool
    latency_ms: float
    policy_source: str = "python_fallback"  # "cedar_cli" | "python_fallback" | "no_policies"
    # Explicit fallback tracking — always populated so callers can audit the engine path.
    fallback_used: bool = False
    fallback_reason: str | None = None  # reason Cedar CLI was not used (if fallback_used)


@dataclass
class _CedarWorker:
    index: int
    process: subprocess.Popen[str]


class CedarProcessPool:
    """Small persistent worker pool for Cedar CLI requests."""

    def __init__(self, cedar_binary: str, size: int | None = None) -> None:
        configured_size = size or _get_cedar_pool_size()
        self.cedar_binary = cedar_binary
        self.size = max(1, configured_size)
        self._semaphore = threading.Semaphore(self.size)
        self._available: queue.Queue[int] = queue.Queue(maxsize=self.size)
        self._workers: list[_CedarWorker] = []
        self._lock = threading.Lock()
        self._closed = False

        for index in range(self.size):
            self._workers.append(self._spawn_worker(index))
            self._available.put(index)

    def _spawn_worker(self, index: int) -> _CedarWorker:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(Path(__file__).resolve()),
                "--cedar-worker",
                self.cedar_binary,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return _CedarWorker(index=index, process=process)

    def _replace_worker(self, index: int) -> _CedarWorker:
        with self._lock:
            old_worker = self._workers[index]
            _terminate_process(old_worker.process)
            worker = self._spawn_worker(index)
            self._workers[index] = worker
            return worker

    def execute(self, payload: dict[str, object]) -> dict[str, object]:
        if self._closed:
            raise RuntimeError("Cedar process pool is closed.")

        self._semaphore.acquire()
        index = self._available.get()
        try:
            worker = self._workers[index]
            if worker.process.poll() is not None:
                worker = self._replace_worker(index)

            proc = worker.process
            stdin = proc.stdin
            stdout = proc.stdout
            stderr = proc.stderr
            if stdin is None or stdout is None or stderr is None:
                raise RuntimeError("Cedar worker pipes are not available.")

            stdin.write(json.dumps(payload) + "\n")
            stdin.flush()
            line = stdout.readline()
            if not line:
                if proc.poll() is not None:
                    error_output = stderr.read().strip()
                    worker = self._replace_worker(index)
                    raise RuntimeError(
                        "Cedar worker exited unexpectedly. "
                        f"exit_code={proc.returncode} stderr={error_output!r}"
                    )
                raise RuntimeError("Cedar worker returned no output.")

            response = json.loads(line)
            if not isinstance(response, dict):
                raise RuntimeError("Invalid Cedar worker response.")
            if response.get("ok") is False:
                raise RuntimeError(str(response.get("error") or "cedar_worker_error"))
            return response
        finally:
            self._available.put(index)
            self._semaphore.release()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            workers = list(self._workers)
            self._workers = []

        for worker in workers:
            _terminate_process(worker.process)


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=1.0)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=1.0)
        except Exception:
            pass


def _get_cedar_pool_size() -> int:
    if _CEDAR_POOL_SIZE_OVERRIDE is not None:
        return _CEDAR_POOL_SIZE_OVERRIDE
    raw = os.environ.get("CEDAR_POOL_SIZE")
    if raw is None:
        return DEFAULT_CEDAR_POOL_SIZE
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "Invalid CEDAR_POOL_SIZE=%r. Falling back to %d.",
            raw,
            DEFAULT_CEDAR_POOL_SIZE,
        )
        return DEFAULT_CEDAR_POOL_SIZE


def configure_cedar_process_pool(pool_size: int) -> None:
    global _CEDAR_POOL_SIZE_OVERRIDE
    _CEDAR_POOL_SIZE_OVERRIDE = max(1, pool_size)


def get_cedar_process_pool(cedar_binary: str | None = None) -> CedarProcessPool:
    global _cedar_pool
    binary = cedar_binary or _find_cedar_cli()
    if binary is None:
        raise RuntimeError("cedar_cli_not_found")

    with _cedar_pool_lock:
        if _cedar_pool is None:
            _cedar_pool = CedarProcessPool(binary, _get_cedar_pool_size())
        return _cedar_pool


def initialize_cedar_process_pool(pool_size: int | None = None) -> CedarProcessPool | None:
    cedar_binary = _find_cedar_cli()
    if cedar_binary is None:
        return None
    if pool_size is not None:
        configure_cedar_process_pool(pool_size)
    pool = get_cedar_process_pool(cedar_binary)
    logger.info("Cedar process pool initialized: %d workers", pool.size)
    return pool


def close_cedar_process_pool() -> None:
    global _cedar_pool
    with _cedar_pool_lock:
        pool = _cedar_pool
        _cedar_pool = None
    if pool is not None:
        pool.close()


def set_cedar_degraded(value: bool) -> None:
    global CEDAR_DEGRADED
    CEDAR_DEGRADED = value


def cedar_cli_available() -> bool:
    return _find_cedar_cli() is not None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_policies(
    cedar_policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    """Evaluate Cedar policies against a request.

    Tries the cedar CLI subprocess first; falls back to Python evaluator.
    Each policy dict must have keys: id, cedar_rule.
    """
    start = time.perf_counter_ns()

    if not cedar_policies:
        # L6: warn so ops can distinguish "no policies seeded yet" from silent deny
        logger.warning(
            "No active policies found for org — all actions will be DENY. "
            "Seed default policies or create at least one policy to allow actions."
        )
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        return EvaluationResult(
            decision="DENY",
            reason="No active policies found. All actions are denied by default.",
            policy_id=None,
            requires_approval=False,
            latency_ms=elapsed,
            policy_source="no_policies",
            fallback_used=False,
        )

    cedar_binary = _find_cedar_cli()
    if cedar_binary:
        try:
            result = _cedar_cli_evaluator(
                cedar_binary, cedar_policies, agent_id, action, resource, context
            )
            result.latency_ms = (time.perf_counter_ns() - start) / 1_000_000
            result.fallback_used = False
            return result
        except Exception as exc:
            fallback_reason = f"cedar_cli_error: {exc}"
            logger.warning(
                "Cedar CLI evaluation failed — using Python fallback. "
                "fallback_reason=%r agent_id=%r action=%r resource=%r",
                fallback_reason,
                agent_id,
                action,
                resource,
            )
            result = _python_evaluator(cedar_policies, agent_id, action, resource, context)
            result.latency_ms = (time.perf_counter_ns() - start) / 1_000_000
            result.fallback_used = True
            result.fallback_reason = fallback_reason
            return result

    fallback_reason = "cedar_cli_not_found"
    logger.debug(
        "Cedar CLI not on PATH — using Python fallback. "
        "Install cedar-policy-cli for authoritative enforcement. "
        "fallback_reason=%r",
        fallback_reason,
    )
    result = _python_evaluator(cedar_policies, agent_id, action, resource, context)
    result.latency_ms = (time.perf_counter_ns() - start) / 1_000_000
    result.fallback_used = True
    result.fallback_reason = fallback_reason
    return result


# ---------------------------------------------------------------------------
# Cedar CLI subprocess path
# ---------------------------------------------------------------------------


def _find_cedar_cli() -> str | None:
    """Return path to the cedar binary, or None if not installed."""
    return shutil.which("cedar")


def _cedar_cli_authorize(
    cedar_binary: str,
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource_id: str,
    context: dict[str, object],
) -> str:
    """Run `cedar authorize` and return 'ALLOW' or 'DENY'. Raises on error."""
    payload = _build_cedar_authorize_payload(policies, agent_id, action, resource_id, context)
    response = get_cedar_process_pool(cedar_binary).execute(payload)
    decision = response.get("decision")
    if decision in {"ALLOW", "DENY"}:
        return str(decision)
    raise RuntimeError(f"Unexpected cedar worker decision: {decision!r}")


def _build_cedar_authorize_payload(
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource_id: str,
    context: dict[str, object],
) -> dict[str, object]:
    policy_text = _cedar_policy_text(policies)
    entities = [
        {"uid": {"type": "Agent", "id": agent_id}, "attrs": {}, "parents": []},
        {
            "uid": {"type": "Resource", "id": resource_id},
            "attrs": {k: v for k, v in context.items() if v is not None},
            "parents": [],
        },
    ]
    request = {
        "principal": f'Agent::"{agent_id}"',
        "action": f'Action::"{action}"',
        "resource": f'Resource::"{resource_id}"',
        "context": context,
    }
    return {
        "command": "authorize",
        "policies": policy_text,
        "entities": entities,
        "request": request,
        "timeout": 5.0,
    }


def _run_cedar_authorize_subprocess(payload: dict[str, object], cedar_binary: str) -> str:
    policy_text = str(payload["policies"])
    entities = payload["entities"]
    request = payload["request"]
    timeout = float(payload.get("timeout") or 5.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        policies_path = Path(tmpdir) / "policies.cedar"
        entities_path = Path(tmpdir) / "entities.json"
        request_path = Path(tmpdir) / "request.cedarauth.json"
        policies_path.write_text(policy_text, encoding="utf-8")
        entities_path.write_text(json.dumps(entities), encoding="utf-8")
        request_path.write_text(json.dumps(request), encoding="utf-8")

        proc = subprocess.run(
            [
                cedar_binary,
                "authorize",
                "--policies",
                str(policies_path),
                "--entities",
                str(entities_path),
                "--request-json",
                str(request_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    output = proc.stdout.strip()
    for line in output.splitlines():
        stripped = line.strip()
        if stripped == "ALLOW" or stripped.startswith("Decision: ALLOW"):
            return "ALLOW"
        if stripped == "DENY" or stripped.startswith("Decision: DENY"):
            return "DENY"
    raise RuntimeError(
        f"Unexpected cedar output: stdout={proc.stdout!r} stderr={proc.stderr!r} "
        f"exit={proc.returncode}"
    )


def _cedar_policy_text(policies: list[dict[str, str]]) -> str:
    """Serialize Cedar policies, expanding approval-gated forbids for CLI parity."""
    rules: list[str] = []
    for policy in policies:
        rule = policy["cedar_rule"].strip()
        rules.append(rule)
        companion_rule = _approval_companion_permit(rule)
        if companion_rule:
            rules.append(companion_rule)
    return "\n\n".join(rules)


def _approval_companion_permit(rule: str) -> str | None:
    """Mirror `forbid ... unless approved` as `permit ... when approved` for Cedar CLI."""
    if "forbid(" not in rule or "unless" not in rule or "approval_status" not in rule:
        return None

    permit_rule = re.sub(r"\bforbid\s*\(", "permit(", rule, count=1)
    return re.sub(r"\bunless\b", "when", permit_rule, count=1)


def _cedar_cli_evaluator(
    cedar_binary: str,
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    """Evaluate using Cedar CLI with APPROVAL_REQUIRED detection via double-eval."""
    decision = _cedar_cli_authorize(cedar_binary, policies, agent_id, action, resource, context)

    if decision == "ALLOW":
        return EvaluationResult(
            decision="ALLOW",
            reason=f"Action '{action}' on '{resource}' is allowed by policy.",
            policy_id=None,  # Cedar CLI does not report which policy matched
            requires_approval=False,
            latency_ms=0,
            policy_source="cedar_cli",
        )

    # DENY — check if injecting approval_status=approved flips it to ALLOW.
    # If yes, a forbid...unless pattern is in play → APPROVAL_REQUIRED.
    if "approval_status" not in context:
        ctx_approved = {**context, "approval_status": "approved"}
        try:
            with_approval = _cedar_cli_authorize(
                cedar_binary, policies, agent_id, action, resource, ctx_approved
            )
            if with_approval == "ALLOW":
                return EvaluationResult(
                    decision="APPROVAL_REQUIRED",
                    reason=f"Action '{action}' on '{resource}' requires human approval.",
                    policy_id=None,
                    requires_approval=True,
                    latency_ms=0,
                    policy_source="cedar_cli",
                )
        except Exception as exc:
            logger.warning("Cedar CLI second-pass (approval check) failed: %s", exc)

    return EvaluationResult(
        decision="DENY",
        reason=f"Action '{action}' on '{resource}' is denied by policy.",
        policy_id=None,
        requires_approval=False,
        latency_ms=0,
        policy_source="cedar_cli",
    )


# ---------------------------------------------------------------------------
# Python regex fallback evaluator
# ---------------------------------------------------------------------------


def _python_evaluator(
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    """Python-based Cedar evaluator for dev/CI without cedar CLI.

    Parses forbid/permit rules and evaluates them.
    Forbid takes precedence over permit (deny-overrides).
    policy_id is populated (unlike the Cedar CLI path).
    """
    forbid_match: dict[str, str] | None = None
    permit_match: dict[str, str] | None = None
    approval_required = False

    for policy in policies:
        rule = policy["cedar_rule"]
        is_forbid = "forbid(" in rule
        is_permit = "permit(" in rule

        if not is_forbid and not is_permit:
            continue

        if _matches_rule(rule, agent_id, action, resource, context):
            if is_forbid:
                has_unless_approval = "approval_status" in rule and "unless" in rule
                if has_unless_approval:
                    approval_status = context.get("approval_status")
                    if approval_status == "approved":
                        permit_match = policy
                        continue
                    approval_required = True
                    forbid_match = policy
                else:
                    forbid_match = policy
            elif is_permit:
                permit_match = policy

    if forbid_match:
        if approval_required:
            return EvaluationResult(
                decision="APPROVAL_REQUIRED",
                reason=f"Action '{action}' on '{resource}' requires human approval.",
                policy_id=forbid_match["id"],
                requires_approval=True,
                latency_ms=0,
            )
        return EvaluationResult(
            decision="DENY",
            reason=f"Action '{action}' on '{resource}' is denied by policy.",
            policy_id=forbid_match["id"],
            requires_approval=False,
            latency_ms=0,
        )

    if permit_match:
        return EvaluationResult(
            decision="ALLOW",
            reason=f"Action '{action}' on '{resource}' is allowed by policy.",
            policy_id=permit_match["id"],
            requires_approval=False,
            latency_ms=0,
        )

    return EvaluationResult(
        decision="DENY",
        reason=f"No matching policy for '{action}' on '{resource}'. Denied by default.",
        policy_id=None,
        requires_approval=False,
        latency_ms=0,
    )


def _matches_rule(
    rule: str,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> bool:
    return _check_action_match(rule, action) and _check_when_clause(rule, resource, context)


def _check_action_match(rule: str, action: str) -> bool:
    all_actions_pattern = r"forbid\s*\(\s*principal\s*,\s*action\s*,"
    if re.search(all_actions_pattern, rule):
        action_specific = re.search(r"action\s*(==|in\s)", rule)
        if not action_specific:
            return True

    exact_pattern = rf'Action::"{re.escape(action)}"'
    return bool(re.search(exact_pattern, rule))


def _check_when_clause(
    rule: str,
    resource: str,
    context: dict[str, object],
) -> bool:
    when_match = re.search(r"when\s*\{([^}]+)\}", rule)
    if not when_match:
        return True

    conditions = when_match.group(1)

    resource_attrs = _extract_attr_pairs(conditions, "resource")
    for attr, expected in resource_attrs.items():
        actual = context.get(attr)
        if actual is None:
            return False
        if isinstance(expected, str) and expected.endswith("*"):
            if not str(actual).startswith(expected.rstrip("*")):
                return False
        elif str(actual) != str(expected):
            return False

    like_patterns = re.findall(r'resource\.(\w+)\s+like\s+"([^"]+)"', conditions)
    for attr, pattern in like_patterns:
        actual = context.get(attr, "")
        regex_pattern = pattern.replace("*", ".*").replace("?", ".")
        if not re.match(regex_pattern, str(actual)):
            return False

    context_attrs = _extract_attr_pairs(conditions, "context")
    for attr, expected in context_attrs.items():
        actual = context.get(attr)
        if actual is None:
            return False
        if str(actual) != str(expected):
            return False

    return True


def _extract_attr_pairs(conditions: str, prefix: str) -> dict[str, str]:
    """Extract `prefix.attr == "value"` pairs from a when-clause body."""
    result: dict[str, str] = {}
    pattern = rf'{prefix}\.(\w+)\s*==\s*"([^"]+)"'
    for match in re.finditer(pattern, conditions):
        result[match.group(1)] = match.group(2)
    return result


def validate_cedar_rule(rule: str) -> ValidationResult:
    stripped = rule.strip()
    if not stripped:
        return ValidationResult(valid=False, error="Cedar rule cannot be empty.")

    cedar_binary = _find_cedar_cli()
    if cedar_binary is not None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "policy.cedar"
            policy_path.write_text(stripped, encoding="utf-8")
            proc = subprocess.run(
                [cedar_binary, "validate", "--policies", str(policy_path)],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        if proc.returncode == 0:
            return ValidationResult(valid=True)
        error = proc.stderr.strip() or proc.stdout.strip() or "cedar_validation_failed"
        return ValidationResult(valid=False, error=error)

    lower = stripped.lower()
    if "permit" not in lower and "forbid" not in lower:
        return ValidationResult(valid=False, error="Cedar rule must contain 'permit' or 'forbid'.")
    for required in ("principal", "action", "resource"):
        if required not in lower:
            return ValidationResult(
                valid=False,
                error=f"Cedar rule must reference '{required}'.",
            )
    return ValidationResult(valid=True)


def _cedar_worker_main(cedar_binary: str) -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise RuntimeError("Worker payload must be a JSON object.")
            if payload.get("command") != "authorize":
                raise RuntimeError(f"Unsupported worker command: {payload.get('command')!r}")
            decision = _run_cedar_authorize_subprocess(payload, cedar_binary)
            sys.stdout.write(json.dumps({"ok": True, "decision": decision}) + "\n")
        except Exception as exc:
            sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}) + "\n")
        sys.stdout.flush()
    return 0


def _main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "--cedar-worker":
        return _cedar_worker_main(argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
