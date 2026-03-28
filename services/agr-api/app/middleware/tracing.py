from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from fastapi import FastAPI

_tracer: Any | None = None


def configure_tracing(settings: Any, app: FastAPI | None = None) -> object | None:
    global _tracer
    if not settings.otel_enabled:
        _tracer = None
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from app.database import engine

        resource = Resource.create(
            {
                "service.name": settings.otel_service_name,
                "service.version": "0.1.0",
                "deployment.mode": settings.deployment_mode,
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
        )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("agr")

        if app is not None:
            FastAPIInstrumentor.instrument_app(app)
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        RedisInstrumentor().instrument()
        return provider
    except Exception as exc:
        logger.warning("OpenTelemetry setup failed: %s", exc)
        _tracer = None
        return None


def get_tracer() -> Any | None:
    return _tracer


def format_traceparent(span: Any) -> str | None:
    if span is None:
        return None
    context = span.get_span_context()
    if not getattr(context, "is_valid", False):
        return None
    return f"00-{context.trace_id:032x}-{context.span_id:016x}-01"
