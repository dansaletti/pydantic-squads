"""Optional OpenTelemetry/Logfire export for the product squad (ADR 0006).

Needs the `ai` and `otel` extras. Off by default: `ProductSquad` never
imports or calls anything here on its own — a consuming project turns it on
explicitly by calling `enable_otel()`. See the README's Observability
section for what this sends and where.
"""


def enable_otel(*, send_to_logfire: bool = False, service_name: str = "pydantic-squads") -> None:
    """Turn on pydantic_ai's native OpenTelemetry instrumentation for every `Agent`.

    Sends full conversation content — user messages, model replies, tool
    call arguments, including knowledge-base note contents — to whatever
    OpenTelemetry backend this configures: Logfire when `send_to_logfire`
    is `True`, or an OTel collector via the usual `OTEL_EXPORTER_*`
    environment variables otherwise. Call this only after reviewing what
    that backend stores and who can access it.
    """
    import logfire

    from pydantic_ai import Agent

    logfire.configure(send_to_logfire=send_to_logfire, service_name=service_name)
    Agent.instrument_all(True)
