"""Optional LangChain callback handler for AGR-oriented logging."""

from __future__ import annotations

import logging
from typing import Any

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError:  # pragma: no cover - optional dependency

    class BaseCallbackHandler:  # type: ignore[no-redef]
        pass


logger = logging.getLogger(__name__)


class AGRCallbackHandler(BaseCallbackHandler):
    def __init__(self, emit_logs: bool = True) -> None:
        self.emit_logs = emit_logs

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        if self.emit_logs:
            logger.info("AGR tool start: %s input=%s", serialized.get("name"), input_str)

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        if self.emit_logs:
            logger.warning("AGR tool error: %s", error)
