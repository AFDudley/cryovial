"""Tests for cryovial.deploy — output capture and namespace wait.

Subprocess.run is mocked at the IO boundary (can't run real laconic-so
or kubectl in tests). We verify observable artifacts: the YAML deploy
record on disk.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from cryovial.deploy import (
    DeployRecord,
    NamespaceTerminatingError,
    ServiceConfig,
    _wait_for_namespace,
    deploy,
)


@pytest.fixture()
def svc() -> ServiceConfig:
    return ServiceConfig(name="test-svc", stack_name="/tmp/test-stack", repo_dir="/tmp")


@pytest.fixture(autouse=True)
def _isolate_deploys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect deploy records to a temp directory."""
    monkeypatch.setattr("cryovial.deploy.DEPLOYS_DIR", tmp_path / "deploys")


def _kubectl_ok() -> subprocess.CompletedProcess[str]:
    """kubectl wait returns 0 — namespace gone or never existed."""
    return subprocess.CompletedProcess(args=["kubectl"], returncode=0, stdout="", stderr="")


def _kubectl_timeout() -> subprocess.CompletedProcess[str]:
    """kubectl wait returns non-zero — namespace still Terminating."""
    return subprocess.CompletedProcess(
        args=["kubectl"], returncode=1, stdout="", stderr="error: Terminating"
    )


def _deploy_result(
    *, stdout: str = "ok\n", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["laconic-so"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --- Output capture: verify the YAML file on disk ---


class TestDeployRecordOnDisk:
    """Deploy records written to disk must contain subprocess output."""

    def test_successful_deploy_writes_output_to_yaml(self, svc: ServiceConfig) -> None:
        """On success, the saved YAML file contains stdout and stderr."""
        record = DeployRecord(service=svc.name)
        calls = [_kubectl_ok(), _deploy_result(stdout="restarted\n", stderr="warn: slow\n")]
        with patch("cryovial.deploy.subprocess.run", side_effect=calls):
            deploy(svc, record=record)

        record.complete()
        saved = yaml.safe_load(record._path().read_text())
        assert saved["stdout"] == "restarted\n"
        assert saved["stderr"] == "warn: slow\n"
        assert saved["status"] == "completed"

    def test_failed_deploy_writes_output_and_error_to_yaml(self, svc: ServiceConfig) -> None:
        """On failure, the saved YAML file contains stdout, stderr, and error."""
        record = DeployRecord(service=svc.name)
        calls = [
            _kubectl_ok(),
            _deploy_result(stdout="crash\n", stderr="OOM\n", returncode=1),
        ]
        with patch("cryovial.deploy.subprocess.run", side_effect=calls):
            with pytest.raises(subprocess.CalledProcessError):
                deploy(svc, record=record)

        # Simulate what server.py does on failure
        error_parts = ["deploy failed"]
        if record.stdout:
            error_parts.append(f"stdout: {record.stdout.strip()}")
        if record.stderr:
            error_parts.append(f"stderr: {record.stderr.strip()}")
        record.fail(error="\n".join(error_parts))

        saved = yaml.safe_load(record._path().read_text())
        assert saved["stdout"] == "crash\n"
        assert saved["stderr"] == "OOM\n"
        assert saved["status"] == "failed"
        assert "OOM" in saved["error"]

    def test_deploy_without_record_does_not_crash(self, svc: ServiceConfig) -> None:
        """When no record is passed, deploy still works (backward compat)."""
        calls = [_kubectl_ok(), _deploy_result()]
        with patch("cryovial.deploy.subprocess.run", side_effect=calls):
            deploy(svc)  # No record= argument, should not raise


# --- Namespace wait: delegates to kubectl wait ---


class TestNamespaceWait:
    """Namespace wait delegates to kubectl wait --for=delete."""

    def test_namespace_gone_proceeds(self) -> None:
        """kubectl wait returns 0 (namespace gone or never existed): proceed."""
        with patch("cryovial.deploy.subprocess.run", return_value=_kubectl_ok()):
            _wait_for_namespace("/tmp/test-stack")  # Should not raise

    def test_namespace_stuck_terminating_raises(self) -> None:
        """kubectl wait times out with Terminating: raise NamespaceTerminatingError."""
        with patch("cryovial.deploy.subprocess.run", return_value=_kubectl_timeout()):
            with pytest.raises(NamespaceTerminatingError, match="still Terminating"):
                _wait_for_namespace("/tmp/test-stack")
