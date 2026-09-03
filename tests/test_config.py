"""The upstream host and the port come from the environment, from nowhere else."""

from __future__ import annotations

import pathlib

from fastapi.testclient import TestClient

from app.config import DEFAULT_PORT, DEFAULT_UPSTREAM_BASE, load_settings
from app.main import create_app

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_defaults(monkeypatch):
    monkeypatch.delenv("FX_UPSTREAM_BASE", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    settings = load_settings()

    assert settings.upstream_base == DEFAULT_UPSTREAM_BASE
    assert settings.port == DEFAULT_PORT


def test_environment_wins(monkeypatch):
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://127.0.0.1:9/")
    monkeypatch.setenv("PORT", "1234")

    settings = load_settings()

    assert settings.upstream_base == "http://127.0.0.1:9"
    assert settings.port == 1234


def test_a_broken_port_does_not_take_the_tool_down(monkeypatch):
    monkeypatch.setenv("PORT", "eight thousand")

    assert load_settings().port == DEFAULT_PORT


def test_the_app_points_at_the_configured_upstream(monkeypatch):
    """Built with no injected client, the service still talks to whatever
    FX_UPSTREAM_BASE says — this is what the reviewer's fake upstream needs."""
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://upstream.example:9999")

    with TestClient(create_app()) as client:
        assert client.app.state.upstream.base_url == "http://upstream.example:9999"


def test_the_real_host_appears_only_as_a_default_in_config():
    """Nothing may hardcode the real upstream host."""
    offenders = [
        path.name
        for path in (REPO_ROOT / "app").glob("*.py")
        if "api.frankfurter.dev" in path.read_text(encoding="utf-8")
    ]

    assert offenders == ["config.py"]
