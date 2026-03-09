from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry import trace
import logging
import os

_otel_initialized = False


def _otel_endpoint():
    return os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")


def setup_otel_tracing():
    """Configure global TracerProvider with OTLP exporter so instrumentations (e.g. ChromaDB) export spans."""
    global _otel_initialized
    if _otel_initialized:
        return
    endpoint = _otel_endpoint()
    if not endpoint:
        return
    base = endpoint.rstrip("/").replace("/v1/logs", "")
    # OTLPSpanExporter uses the endpoint as-is (no path appended), so we must include /v1/traces
    traces_endpoint = f"{base}/v1/traces"
    trace_provider = TracerProvider()
    trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint)))
    trace.set_tracer_provider(trace_provider)
    _otel_initialized = True


def setup_otel_logging():
    global _otel_initialized
    if _otel_initialized:
        return
    endpoint = _otel_endpoint()
    if not endpoint:
        _otel_initialized = True
        return
    setup_otel_tracing()
    # Ensure URL path for logs (OTEL_EXPORTER_OTLP_ENDPOINT is base)
    if endpoint.rstrip("/").endswith("/v1/logs"):
        logs_endpoint = endpoint
    else:
        logs_endpoint = f"{endpoint.rstrip('/')}/v1/logs"
    exporter = OTLPLogExporter(endpoint=logs_endpoint)
    logger_provider = LoggerProvider()
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    _otel_initialized = True