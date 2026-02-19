from __future__ import annotations

from types import SimpleNamespace

import subprocess
import pytest

from tools.dashboard.backend.services.runtime import RuntimeStateService


def test_parse_launchctl_running_state() -> None:
    output = """
state = running
pid = 9999
"""
    state, pid, raw = RuntimeStateService._parse_launchctl_output(output)
    assert state == "running"
    assert pid == "9999"
    assert raw == output[:4096]


def test_collect_stopped_when_service_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(*_args, **_kwargs) -> SimpleNamespace:
        return SimpleNamespace(returncode=3, stdout="", stderr="Could not find service\n")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    payload = RuntimeStateService("com.example.bot").collect()
    assert payload["state"] == "stopped"
    assert payload["running"] is False
    assert payload["exit_code"] == 3


def test_collect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["launchctl"], timeout=6)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    payload = RuntimeStateService("com.example.bot").collect()
    assert payload["state"] == "unknown"
    assert payload["running"] is False
    assert payload["raw"] == "launchctl timed out"
