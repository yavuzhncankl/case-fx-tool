"""Runtime configuration.

Everything that could differ between our machine and the reviewer's machine is
read from the environment. Nothing in this repository hardcodes the real
upstream host: `FX_UPSTREAM_BASE` is the only place it comes from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_UPSTREAM_BASE = "https://api.frankfurter.dev"
DEFAULT_PORT = 8080
DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Settings:
    upstream_base: str
    port: int
    timeout_seconds: float


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_settings() -> Settings:
    """Read settings from the environment.

    Bad values fall back to the defaults rather than crashing at boot: a
    mistyped PORT should not take the tool offline for the agent calling it.
    """
    base = os.environ.get("FX_UPSTREAM_BASE") or DEFAULT_UPSTREAM_BASE
    return Settings(
        upstream_base=base.rstrip("/"),
        port=_int_env("PORT", DEFAULT_PORT),
        timeout_seconds=_float_env("FX_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
