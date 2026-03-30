"""Tests for cryovial.cli — env var fallback for --secret and --config."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from cryovial.cli import main


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


def test_secret_from_env_var(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CRYOVIAL_SECRET env var is used when --secret is not provided."""
    monkeypatch.setenv("CRYOVIAL_SECRET", "env-secret-value")
    with patch("cryovial.cli.WebhookServer") as mock_server:
        mock_server.return_value.run.side_effect = SystemExit(0)
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["cryovial", "serve", "--config", str(config_file)]):
                main()
        mock_server.assert_called_once()
        assert mock_server.call_args.kwargs["secret"] == "env-secret-value"


def test_secret_flag_overrides_env(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--secret flag takes precedence over CRYOVIAL_SECRET env var."""
    monkeypatch.setenv("CRYOVIAL_SECRET", "env-secret-value")
    with patch("cryovial.cli.WebhookServer") as mock_server:
        mock_server.return_value.run.side_effect = SystemExit(0)
        with pytest.raises(SystemExit):
            with patch(
                "sys.argv",
                ["cryovial", "serve", "--config", str(config_file), "--secret", "flag-secret"],
            ):
                main()
        mock_server.assert_called_once()
        assert mock_server.call_args.kwargs["secret"] == "flag-secret"


def test_missing_secret_errors(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing both --secret and CRYOVIAL_SECRET produces an error."""
    monkeypatch.delenv("CRYOVIAL_SECRET", raising=False)
    with patch("sys.argv", ["cryovial", "serve", "--config", str(config_file)]):
        result = main()
    assert result == 1


def test_config_from_env_var(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CRYOVIAL_CONFIG env var is used when --config is not provided."""
    monkeypatch.setenv("CRYOVIAL_CONFIG", str(config_file))
    monkeypatch.setenv("CRYOVIAL_SECRET", "test-secret")
    with patch("cryovial.cli.WebhookServer") as mock_server:
        mock_server.return_value.run.side_effect = SystemExit(0)
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["cryovial", "serve"]):
                main()
        mock_server.assert_called_once()
