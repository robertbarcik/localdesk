"""OpenTelemetry tracing setup — exports spans to Dynatrace via OTLP/HTTP."""

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

logger = logging.getLogger(__name__)

_DT_ENDPOINT = "https://ksl51844.live.dynatrace.com/api/v2/otlp/v1/traces"
_DT_API_TOKEN = (
    "dt0c01.CM2P657FTNSOO2V62ZE3I4MS"
    ".QUQ3DHOQX3VLFHDROBCVIONSDD3P65KRXZPOCRUX6Y3OTT67OYV2C4SWL6PX7QZN"
)


def init_tracing() -> trace.Tracer:
    """Initialize OTel tracer with Dynatrace OTLP exporter. Returns the app tracer."""
    resource = Resource.create(
        {
            "service.name": "mu",
            "service.version": "1.0.0",
            "deployment.environment": "demo",
        }
    )

    exporter = OTLPSpanExporter(
        endpoint=_DT_ENDPOINT,
        headers={"Authorization": f"Api-Token {_DT_API_TOKEN}"},
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    logger.info("OpenTelemetry tracing initialized — exporting to Dynatrace")
    return trace.get_tracer("mu.app", "1.0.0")


# Module-level tracer — import this from other modules
tracer = init_tracing()
