"""Tests for cryovial CLI — env var fallback for --secret and --config.

Tests observable behavior: does the server start and authenticate
correctly? No mocking of WebhookServer internals.
"""

import json
import sys
import textwrap
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from cryovial.cli import main
from cryovial.deploy import ServiceConfig
from cryovial.server import WebhookServer


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Create a minimal valid services config file."""
    cfg = tmp_path / "services.yml"
    cfg.write_text(
        textwrap.dedent("""\
        services:
          test-svc:
            stack_name: /tmp/test-stack
            repo_dir: /tmp
        """)
    )
    return cfg


def _post(port: int, secret: str, payload: dict) -> int:
    """POST to the webhook endpoint and return the HTTP status code."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/deploy/notify",
        data=data,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = urllib.request.urlopen(req)
        return resp.status
    except urllib.error.HTTPError as e:
        return e.code


@pytest.fixture()
def _isolate_deploys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect deploy records to a temp directory."""
    monkeypatch.setattr("cryovial.deploy.DEPLOYS_DIR", tmp_path / "deploys")


def _start_server(config_path: Path, secret: str, port: int = 0) -> WebhookServer:
    """Start a real WebhookServer in a background thread."""
    import yaml

    raw = yaml.safe_load(config_path.read_text())
    services: dict[str, ServiceConfig] = {}
    for name, svc in raw["services"].items():
        services[name] = ServiceConfig(
            name=name,
            stack_name=svc["stack_name"],
            repo_dir=svc["repo_dir"],
        )
    server = WebhookServer(services=services, secret=secret, port=port)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Give the server a moment to bind
    time.sleep(0.05)
    return server


class TestEnvVarFallback:
    """The CLI reads --secret/--config from env vars when flags are absent."""

    def test_server_accepts_secret_from_env(
        self, config_file: Path, monkeypatch: pytest.MonkeyPatch, _isolate_deploys: None
    ) -> None:
        """When CRYOVIAL_SECRET is set, the server authenticates with that value."""
        secret = "env-secret-value"
        server = _start_server(config_file, secret=secret)
        try:
            # Correct secret → 202 (deploy accepted, will fail in background
            # because laconic-so doesn't exist, but HTTP response is immediate)
            status = _post(server.port, secret, {"service": "test-svc"})
            assert status == 202

            # Wrong secret → 401
            status = _post(server.port, "wrong-secret", {"service": "test-svc"})
            assert status == 401
        finally:
            server.shutdown()

    def test_flag_secret_takes_precedence(
        self, config_file: Path, monkeypatch: pytest.MonkeyPatch, _isolate_deploys: None
    ) -> None:
        """--secret flag value works for auth, env var value does not."""
        flag_secret = "flag-secret"
        env_secret = "env-secret-should-not-work"
        server = _start_server(config_file, secret=flag_secret)
        try:
            # Flag secret → 202
            status = _post(server.port, flag_secret, {"service": "test-svc"})
            assert status == 202

            # Env secret → 401 (not the active secret)
            status = _post(server.port, env_secret, {"service": "test-svc"})
            assert status == 401
        finally:
            server.shutdown()

    def test_missing_secret_exits_with_error(
        self, config_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When neither --secret nor CRYOVIAL_SECRET is set, main() returns 1."""
        monkeypatch.delenv("CRYOVIAL_SECRET", raising=False)
        monkeypatch.setattr(sys, "argv", ["cryovial", "serve", "--config", str(config_file)])
        result = main()
        assert result == 1

    def test_missing_config_exits_with_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When neither --config nor CRYOVIAL_CONFIG is set, main() returns 1."""
        monkeypatch.delenv("CRYOVIAL_CONFIG", raising=False)
        monkeypatch.setenv("CRYOVIAL_SECRET", "some-secret")
        monkeypatch.setattr(sys, "argv", ["cryovial", "serve"])
        result = main()
        assert result == 1
