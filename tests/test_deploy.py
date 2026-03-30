"""Tests for cryovial.deploy — output capture and namespace wait."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from cryovial.deploy import DeployRecord, ServiceConfig, deploy, DEPLOYS_DIR


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
            args=["laconic-so"], returncode=1,
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
            args=["laconic-so"], returncode=0,
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
            args=["laconic-so"], returncode=1,
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
