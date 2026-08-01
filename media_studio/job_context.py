"""
Active Job / Listing name for the current generate (thread-safe via contextvars).

UI sets the name on StudioState and enters ``job_name_scope`` around background
work so ``job_media_dir`` / ``append_history`` pick it up without every caller
passing an extra arg. Empty name = default flat/dated outputs (no jobs/ folder).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

_job_name: ContextVar[str] = ContextVar("ams_job_name", default="")


def current_job_name() -> str:
    """Return active job/listing label (may be empty)."""
    return (_job_name.get() or "").strip()


def set_job_name(name: str | None) -> Token:
    """Set context value; returns token for reset."""
    return _job_name.set((name or "").strip())


def reset_job_name(token: Token) -> None:
    _job_name.reset(token)


@contextmanager
def job_name_scope(name: str | None) -> Iterator[str]:
    """Temporarily set job name for nested generate / history writes."""
    token = set_job_name(name)
    try:
        yield current_job_name()
    finally:
        reset_job_name(token)


@contextmanager
def state_job_scope(state: object) -> Iterator[str]:
    """Use ``state.job_name`` for the duration of a generate call."""
    name = getattr(state, "job_name", None) if state is not None else None
    with job_name_scope(name) as active:
        yield active


async def to_thread_with_job(state: object, fn, /, *args, **kwargs):
    """
    ``asyncio.to_thread`` with Job / Listing context propagated into the worker.

    Use for all generate paths so outputs land under jobs/<slug>/ when set.
    """
    import asyncio

    def _runner():
        with state_job_scope(state):
            return fn(*args, **kwargs)

    return await asyncio.to_thread(_runner)
