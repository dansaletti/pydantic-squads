import inspect

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")
pytest.importorskip("logfire", reason="requires the 'otel' extra: uv sync --extra otel")

from pydantic_squads.product import assembly
from pydantic_squads.product.otel import enable_otel


def test_enable_otel_is_never_called_automatically_by_assembly():
    """Nothing in product.assembly references enable_otel or imports the otel module — it is opt-in only"""
    source = inspect.getsource(assembly)
    assert "enable_otel" not in source
    assert "otel" not in source


def test_enable_otel_configures_logfire_and_instruments_agents(monkeypatch):
    """enable_otel() configures logfire and turns on pydantic_ai's Agent instrumentation"""
    calls = {}

    def fake_configure(**kwargs):
        calls["configure"] = kwargs

    monkeypatch.setattr("logfire.configure", fake_configure)

    from pydantic_ai import Agent

    instrumented = {}
    monkeypatch.setattr(
        Agent, "instrument_all", staticmethod(lambda instrument=True: instrumented.setdefault("value", instrument))
    )

    enable_otel(send_to_logfire=False, service_name="test-service")

    assert calls["configure"] == {"send_to_logfire": False, "service_name": "test-service"}
    assert instrumented["value"] is True
