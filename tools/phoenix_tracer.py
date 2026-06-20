"""Optional Arize Phoenix tracing integration.

Phoenix (https://github.com/Arize-ai/phoenix) is a local LLM observability tool. When
enabled, our LLM calls export OpenTelemetry traces to a running `phoenix serve` instance
so you can inspect every prompt, response, latency, and token count in a web UI.

This is OPTIONAL — only activates if config.tracing.enabled is true AND the optional
packages are installed:
    pip install arize-phoenix-otel openinference-instrumentation-ollama

Otherwise it's a no-op.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def maybe_setup_phoenix(config: dict) -> bool:
    """Initialize Arize Phoenix tracing if enabled and deps available. Returns True if active."""
    tracing = config.get("tracing", {})
    if not tracing.get("enabled", False):
        return False

    endpoint = tracing.get("endpoint", "http://localhost:6006/v1/traces")
    project_name = tracing.get("project_name", "ollama-local-research-agent")

    try:
        from phoenix.otel import register
        tracer_provider = register(
            project_name=project_name,
            endpoint=endpoint,
        )
    except ImportError:
        log.warning(
            "Phoenix tracing enabled but `arize-phoenix-otel` is not installed. "
            "Run: pip install arize-phoenix-otel"
        )
        return False
    except Exception as e:
        log.warning("Phoenix register failed (%s) — continuing without tracing.", e)
        return False

    # Optionally instrument Ollama HTTP calls
    try:
        from openinference.instrumentation.ollama import OllamaInstrumentor
        OllamaInstrumentor().instrument(tracer_provider=tracer_provider)
        log.info("Phoenix tracing active: project=%s endpoint=%s", project_name, endpoint)
    except ImportError:
        log.info(
            "Phoenix base tracing active. For Ollama auto-instrumentation: "
            "pip install openinference-instrumentation-ollama"
        )
    except Exception as e:
        log.warning("Ollama instrumentation failed: %s", e)

    return True
