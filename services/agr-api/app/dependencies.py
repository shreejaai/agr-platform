"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from collections.abc import Callable

# Role hierarchy: higher index = more permissions
_ROLE_RANK: dict[str, int] = {"viewer": 0, "operator": 1, "admin": 2}


def require_role(min_role: str) -> Callable[..., Any]:
    """Return a FastAPI dependency that enforces a minimum RBAC role.

    Usage:
        @router.delete("/foo", dependencies=[Depends(require_role("operator"))])
    """

    async def _check(request: Request) -> None:
        role: str = getattr(request.state, "role", "admin")
        if _ROLE_RANK.get(role, 0) < _ROLE_RANK.get(min_role, 0):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{role}' is insufficient. Required: '{min_role}' or higher.",
            )

    return _check
