"""Langfuse v5 tracing: one trace per trip run (session = trip id), one section per agent.

    trip-run  (trace: session_id=trip_id, metadata: destination, revision)
    ├── guard / brief / destination ... finalize        (agent spans)
    │   ├── mcp.places.search_places                    (tool)
    │   ├── rag.search                                  (retriever)
    │   └── ChatGroq                                    (generation, via the LangChain callback)
    └── scores: Faithfulness, Answer relevancy, ..., Overall

PII is masked out of every input/output/metadata field before export. With no keys (or offline)
every call is a no-op, so the code path is identical.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from voyager.config import Settings, get_settings

logger = logging.getLogger(__name__)


class _Noop:
    id = None
    trace_id = None

    def update(self, **_: Any) -> _Noop:
        return self


NOOP = _Noop()


def _mask(*, data: Any, **_: Any) -> Any:
    from voyager.guardrails.pii import redact_any

    try:
        return redact_any(data)
    except Exception:  # noqa: BLE001 - masking must never drop a trace
        return data


class Tracer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: Any = None
        if settings.langfuse_enabled:
            try:
                from langfuse import Langfuse

                kwargs: dict[str, Any] = {}
                try:
                    from langfuse.span_filter import is_langfuse_span

                    kwargs["should_export_span"] = is_langfuse_span  # skip raw MCP/httpx OTel spans
                except ImportError:
                    pass
                self.client = Langfuse(
                    public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key,
                    base_url=settings.langfuse_host, environment=settings.langfuse_environment,
                    mask=_mask, **kwargs,
                )
            except Exception as exc:  # noqa: BLE001 - tracing must never break a run
                logger.warning("langfuse disabled: %s", exc)
                self.client = None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @contextmanager
    def run_trace(self, *, trip_id: str, revision: int, input: Any, user_id: str | None,
                  metadata: dict[str, Any], name: str = "trip-run", tags: list[str] | None = None) -> Iterator[Any]:
        """One trace per run. `name`/`tags` let other entry points (the chat assistant) reuse it."""
        if not self.enabled:
            yield NOOP
            return
        try:
            from langfuse import propagate_attributes

            obs_cm = self.client.start_as_current_observation(
                name=name, as_type="chain", input=input, metadata=metadata)
            attrs_cm = propagate_attributes(
                trace_name=name, session_id=trip_id, user_id=user_id,
                tags=tags or ["voyager", f"rev{revision}"], metadata={k: str(v)[:200] for k, v in metadata.items()})
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse trace failed: %s", exc)
            yield NOOP
            return
        with obs_cm as root, attrs_cm:
            yield root

    @contextmanager
    def section(self, name: str, as_type: str = "span", input: Any = None, metadata: Any = None,
                **kwargs: Any) -> Iterator[Any]:
        if not self.enabled:
            yield NOOP
            return
        try:
            cm = self.client.start_as_current_observation(
                name=name, as_type=as_type, input=input, metadata=metadata, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse section %s failed: %s", name, exc)
            cm = nullcontext(NOOP)
        with cm as obs:
            yield obs

    def callbacks(self) -> list[Any]:
        """LangChain callbacks: every ChatGroq call becomes a Langfuse generation (tokens, latency)."""
        if not self.enabled:
            return []
        try:
            from langfuse.langchain import CallbackHandler

            return [CallbackHandler(public_key=self.settings.langfuse_public_key)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse callback unavailable: %s", exc)
            return []

    def current_trace_id(self) -> str | None:
        if not self.enabled:
            return None
        try:
            return self.client.get_current_trace_id()
        except Exception:  # noqa: BLE001
            return None

    def trace_context(self) -> dict[str, str] | None:
        """W3C-style ids handed to a remote agent so its spans join this trace."""
        if not self.enabled:
            return None
        try:
            trace_id = self.client.get_current_trace_id()
            span_id = self.client.get_current_observation_id()
        except Exception:  # noqa: BLE001
            return None
        if not trace_id:
            return None
        return {"trace_id": trace_id, **({"parent_span_id": span_id} if span_id else {})}

    def score(self, *, trace_id: str | None, name: str, value: float, comment: str | None = None) -> bool:
        if not (self.enabled and trace_id) or value is None:
            return False
        try:
            self.client.create_score(trace_id=trace_id, name=name, value=float(value),
                                     data_type="NUMERIC", comment=comment)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse score %s failed: %s", name, exc)
            return False

    def trace_url(self, trace_id: str | None) -> str | None:
        if not (self.enabled and trace_id):
            return None
        try:
            return self.client.get_trace_url(trace_id=trace_id)
        except Exception:  # noqa: BLE001
            return None

    def flush(self) -> None:
        if self.enabled:
            try:
                self.client.flush()
            except Exception as exc:  # noqa: BLE001
                logger.warning("langfuse flush failed: %s", exc)


_TRACER: Tracer | None = None


def get_tracer() -> Tracer:
    global _TRACER
    if _TRACER is None:
        _TRACER = Tracer(get_settings())
    return _TRACER


def set_tracer(tracer: Tracer | None) -> None:
    global _TRACER
    _TRACER = tracer
