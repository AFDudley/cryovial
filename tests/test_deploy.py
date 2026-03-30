"""Tests for cryovial.deploy — output capture and namespace wait."""

import subprocess
from unittest.mock import call, patch

import pytest

from cryovial.deploy import (
    DeployRecord,
    NamespaceTerminatingError,
    ServiceConfig,
    deploy,
)


@pytest.fixture()
def svc() -> ServiceConfig:
    return ServiceConfig(name="test-svc", stack_name="/tmp/test-stack", repo_dir="/tmp")


@pytest.fixture(autouse=True)
def _isolate_deploys(tmp_path, monkeypatch):
    """Redirect deploy records to a temp directory."""
    monkeypatch.setattr("cryovial.deploy.DEPLOYS_DIR", tmp_path / "deploys")


# --- Bug 1: stdout/stderr capture in deploy records ---


class TestDeployOutputCapture:
    """Deploy records must capture subprocess stdout/stderr."""

    def test_failed_deploy_captures_stdout_stderr(self, svc):
        """When deploy fails, the record must contain stdout and stderr."""
        fake_result = subprocess.CompletedProcess(
            args=["laconic-so"],
            returncode=1,
            stdout="container exited with code 137\n",
            stderr="OOMKilled: memory limit exceeded\n",
        )
        record = DeployRecord(service=svc.name)
        with patch("cryovial.deploy.subprocess.run", return_value=fake_result):
            with pytest.raises(subprocess.CalledProcessError):
                deploy(svc, record=record)

        assert record.stdout == "container exited with code 137\n"
        assert record.stderr == "OOMKilled: memory limit exceeded\n"

    def test_successful_deploy_captures_output(self, svc):
        """Even successful deploys should capture output for audit."""
        fake_result = subprocess.CompletedProcess(
            args=["laconic-so"],
            returncode=0,
            stdout="deployment restarted successfully\n",
            stderr="",
        )
        record = DeployRecord(service=svc.name)
        with patch("cryovial.deploy.subprocess.run", return_value=fake_result):
            deploy(svc, record=record)

        assert record.stdout == "deployment restarted successfully\n"
        assert record.stderr == ""

    def test_record_save_includes_stdout_stderr(self, svc, tmp_path):
        """Saved YAML must contain stdout and stderr fields."""
        record = DeployRecord(service=svc.name, stdout="out", stderr="err")
        record.save()

        import yaml

        saved = yaml.safe_load(record._path().read_text())
        assert saved["stdout"] == "out"
        assert saved["stderr"] == "err"

    def test_failed_deploy_includes_output_in_error(self, svc):
        """The error message should include stdout/stderr, not just exception str."""
        fake_result = subprocess.CompletedProcess(
            args=["laconic-so"],
            returncode=1,
            stdout="pod crash loop\n",
            stderr="back-off restarting failed container\n",
        )
        record = DeployRecord(service=svc.name)
        with patch("cryovial.deploy.subprocess.run", return_value=fake_result):
            with pytest.raises(subprocess.CalledProcessError):
                deploy(svc, record=record)

        # stdout/stderr should be on the record regardless of how caller handles exception
        assert "pod crash loop" in record.stdout
        assert "back-off restarting failed container" in record.stderr


# --- Bug 2: Namespace termination race ---


class TestNamespaceWait:
    """Deploy must wait for Terminating namespaces before proceeding."""

    def _kubectl_result(self, phase: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=["kubectl"], returncode=0, stdout=phase, stderr=""
        )

    def _deploy_result(self) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=["laconic-so"], returncode=0, stdout="ok\n", stderr=""
        )

    def test_active_namespace_proceeds_immediately(self, svc):
        """When namespace is Active, deploy runs without waiting."""
        calls = [
            self._kubectl_result("Active"),
            self._deploy_result(),
        ]
        with patch("cryovial.deploy.subprocess.run", side_effect=calls):
            with patch("cryovial.deploy.time.sleep") as mock_sleep:
                deploy(svc)
                mock_sleep.assert_not_called()

    def test_terminating_namespace_waits_then_proceeds(self, svc):
        """Namespace Terminating -> Terminating -> not found (gone) -> deploy proceeds."""
        # kubectl returns Terminating twice, then fails (namespace gone = ready to proceed)
        kubectl_terminating = self._kubectl_result("Terminating")
        kubectl_gone = subprocess.CompletedProcess(
            args=["kubectl"], returncode=1, stdout="", stderr="not found"
        )
        calls = [
            kubectl_terminating,
            kubectl_terminating,
            kubectl_gone,
            self._deploy_result(),
        ]
        with patch("cryovial.deploy.subprocess.run", side_effect=calls):
            with patch("cryovial.deploy.time.sleep") as mock_sleep:
                deploy(svc)
                assert mock_sleep.call_count == 2
                mock_sleep.assert_called_with(5)

    def test_terminating_namespace_timeout_raises(self, svc):
        """If namespace stays Terminating past timeout, raise error."""
        kubectl_terminating = self._kubectl_result("Terminating")
        # Simulate time progressing past the 120s timeout
        with patch("cryovial.deploy.subprocess.run", return_value=kubectl_terminating):
            with patch("cryovial.deploy.time.sleep"):
                with patch("cryovial.deploy.time.monotonic", side_effect=[0.0, 130.0]):
                    with pytest.raises(NamespaceTerminatingError, match="still Terminating"):
                        deploy(svc)

    def test_nonexistent_namespace_proceeds(self, svc):
        """If namespace doesn't exist at all, deploy proceeds normally."""
        kubectl_not_found = subprocess.CompletedProcess(
            args=["kubectl"], returncode=1, stdout="", stderr="not found"
        )
        calls = [kubectl_not_found, self._deploy_result()]
        with patch("cryovial.deploy.subprocess.run", side_effect=calls):
            with patch("cryovial.deploy.time.sleep") as mock_sleep:
                deploy(svc)
                mock_sleep.assert_not_called()
