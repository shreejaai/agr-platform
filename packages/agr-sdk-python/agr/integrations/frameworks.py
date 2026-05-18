"""Generic AGR integration helpers for agent frameworks."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Literal, ParamSpec, TypeVar, cast

from agr.client import (
    AGRClient,
    AGRError,
    AsyncAGRClient,
    EvaluationResult,
    PendingApprovalResult,
)

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

ApprovalMode = Literal["block", "non_blocking"]

ActionResolver = str | Callable[..., str] | None
ResourceResolver = str | Callable[..., str | None] | None
ContextResolver = dict[str, object] | Callable[..., dict[str, object] | None] | None


def _resolve_action(action: ActionResolver, default: str, *args: object, **kwargs: object) -> str:
    if callable(action):
        return str(action(*args, **kwargs))
    if isinstance(action, str) and action:
        return action
    return default


def _resolve_resource(
    resource: ResourceResolver, fallback: str, *args: object, **kwargs: object
) -> str:
    if callable(resource):
        value = resource(*args, **kwargs)
        return str(value) if value else fallback
    if isinstance(resource, str) and resource:
        return resource
    return fallback


def _resolve_context(
    default_context: dict[str, object],
    context: ContextResolver,
    *args: object,
    **kwargs: object,
) -> dict[str, object]:
    merged = dict(default_context)
    resolved: dict[str, object] | None

    resolved = context(*args, **kwargs) if callable(context) else context

    if resolved:
        merged.update(resolved)
    return merged


class AGRPolicyEnforcer:
    """Synchronous governance wrapper for agent tools and framework hooks."""

    def __init__(
        self,
        client: AGRClient,
        agent_id: str,
        *,
        default_context: dict[str, object] | None = None,
    ) -> None:
        self.client = client
        self.agent_id = agent_id
        self.default_context = default_context or {}

    def evaluate(
        self,
        *,
        action: str,
        resource: str | None = None,
        context: dict[str, object] | None = None,
    ) -> EvaluationResult:
        target = resource or action
        merged_context = dict(self.default_context)
        if context:
            merged_context.update(context)
        return self.client.evaluate(
            agent=self.agent_id,
            action=action,
            resource=target,
            context=merged_context,
        )

    def before_tool(
        self,
        *,
        action: str,
        resource: str | None = None,
        context: dict[str, object] | None = None,
        approval_timeout: float = 3600.0,
        poll_interval: float = 2.0,
        mode: ApprovalMode = "block",
    ) -> EvaluationResult | PendingApprovalResult:
        """Run policy enforcement before tool execution.

        ``mode='block'`` (default, backwards-compatible): blocks the calling
        thread until the approval is decided, then raises on rejection.
        ``mode='non_blocking'``: returns a :class:`PendingApprovalResult` so
        the caller can hand the approval_id off to whatever orchestration
        layer it controls (queue, durable workflow, UI hand-off, ...).
        """
        result = self.evaluate(action=action, resource=resource, context=context)

        if result.denied:
            raise AGRError(f"Action '{action}' denied by AGR policy: {result.reason}")

        if result.requires_approval:
            if not result.approval_id:
                raise AGRError(
                    f"Action '{action}' requires approval, but the API returned no approval_id."
                )
            if mode == "non_blocking":
                return PendingApprovalResult(
                    approval_id=result.approval_id,
                    action=action,
                    resource=resource or action,
                    reason=result.reason,
                    eval_id=result.eval_id,
                )
            logger.info(
                "Action '%s' requires approval (id=%s). Waiting...",
                action,
                result.approval_id,
            )
            approved = self.client.wait_for_approval(
                result.approval_id,
                poll_interval=poll_interval,
                timeout=approval_timeout,
            )
            if not approved:
                raise AGRError(f"Action '{action}' was rejected during approval.")

        return result

    def wrap(
        self,
        func: Callable[P, R] | None = None,
        *,
        action: ActionResolver = None,
        resource: ResourceResolver = None,
        context: ContextResolver = None,
        approval_timeout: float = 3600.0,
        poll_interval: float = 2.0,
        mode: ApprovalMode = "block",
    ) -> (
        Callable[[Callable[P, R]], Callable[P, R | PendingApprovalResult]]
        | Callable[P, R | PendingApprovalResult]
    ):
        """Wrap a callable so AGR policies are enforced before execution.

        With ``mode='non_blocking'`` the wrapped function returns a
        :class:`PendingApprovalResult` instead of invoking the inner
        callable when AGR requires approval; the caller is responsible
        for re-invoking after :meth:`AGRClient.await_decision` resolves.
        """

        def decorator(inner: Callable[P, R]) -> Callable[P, R | PendingApprovalResult]:
            @functools.wraps(inner)
            def wrapped(*args: P.args, **kwargs: P.kwargs) -> R | PendingApprovalResult:
                resolved_action = _resolve_action(action, inner.__name__, *args, **kwargs)
                resolved_resource = _resolve_resource(resource, resolved_action, *args, **kwargs)
                resolved_context = _resolve_context(self.default_context, context, *args, **kwargs)
                outcome = self.before_tool(
                    action=resolved_action,
                    resource=resolved_resource,
                    context=resolved_context,
                    approval_timeout=approval_timeout,
                    poll_interval=poll_interval,
                    mode=mode,
                )
                if isinstance(outcome, PendingApprovalResult):
                    return outcome
                return inner(*args, **kwargs)

            return wrapped

        if func is None:
            return decorator
        return decorator(func)


class AsyncAGRPolicyEnforcer:
    """Async governance wrapper for async agent tools and framework hooks."""

    def __init__(
        self,
        client: AsyncAGRClient,
        agent_id: str,
        *,
        default_context: dict[str, object] | None = None,
    ) -> None:
        self.client = client
        self.agent_id = agent_id
        self.default_context = default_context or {}

    async def evaluate(
        self,
        *,
        action: str,
        resource: str | None = None,
        context: dict[str, object] | None = None,
    ) -> EvaluationResult:
        target = resource or action
        merged_context = dict(self.default_context)
        if context:
            merged_context.update(context)
        return await self.client.evaluate(
            agent=self.agent_id,
            action=action,
            resource=target,
            context=merged_context,
        )

    async def before_tool(
        self,
        *,
        action: str,
        resource: str | None = None,
        context: dict[str, object] | None = None,
        approval_timeout: float = 3600.0,
        poll_interval: float = 2.0,
        mode: ApprovalMode = "block",
    ) -> EvaluationResult | PendingApprovalResult:
        """Run policy enforcement before async tool execution."""
        result = await self.evaluate(action=action, resource=resource, context=context)

        if result.denied:
            raise AGRError(f"Action '{action}' denied by AGR policy: {result.reason}")

        if result.requires_approval:
            if not result.approval_id:
                raise AGRError(
                    f"Action '{action}' requires approval, but the API returned no approval_id."
                )
            if mode == "non_blocking":
                return PendingApprovalResult(
                    approval_id=result.approval_id,
                    action=action,
                    resource=resource or action,
                    reason=result.reason,
                    eval_id=result.eval_id,
                )
            logger.info(
                "Action '%s' requires approval (id=%s). Waiting...",
                action,
                result.approval_id,
            )
            approved = await self.client.wait_for_approval(
                result.approval_id,
                poll_interval=poll_interval,
                timeout=approval_timeout,
            )
            if not approved:
                raise AGRError(f"Action '{action}' was rejected during approval.")

        return result

    def wrap(
        self,
        func: Callable[P, Awaitable[R]] | None = None,
        *,
        action: ActionResolver = None,
        resource: ResourceResolver = None,
        context: ContextResolver = None,
        approval_timeout: float = 3600.0,
        poll_interval: float = 2.0,
        mode: ApprovalMode = "block",
    ) -> (
        Callable[
            [Callable[P, Awaitable[R]]],
            Callable[P, Awaitable[R | PendingApprovalResult]],
        ]
        | Callable[P, Awaitable[R | PendingApprovalResult]]
    ):
        """Wrap an async callable so AGR policies are enforced before execution."""

        def decorator(
            inner: Callable[P, Awaitable[R]],
        ) -> Callable[P, Awaitable[R | PendingApprovalResult]]:
            @functools.wraps(inner)
            async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R | PendingApprovalResult:
                resolved_action = _resolve_action(action, inner.__name__, *args, **kwargs)
                resolved_resource = _resolve_resource(resource, resolved_action, *args, **kwargs)
                resolved_context = _resolve_context(self.default_context, context, *args, **kwargs)
                outcome = await self.before_tool(
                    action=resolved_action,
                    resource=resolved_resource,
                    context=resolved_context,
                    approval_timeout=approval_timeout,
                    poll_interval=poll_interval,
                    mode=mode,
                )
                if isinstance(outcome, PendingApprovalResult):
                    return outcome
                return await inner(*args, **kwargs)

            return cast(
                "Callable[P, Awaitable[R | PendingApprovalResult]]",
                wrapped,
            )

        if func is None:
            return decorator
        return decorator(func)
