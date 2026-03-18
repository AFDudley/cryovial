"""Deploy operations for cluster management.

When a SHA-tagged image is provided, restarts the deployment with
that specific image via laconic-so --image flag. Falls back to a
plain laconic-so deployment restart when no image is specified.

Deploy records are written to ~/.cryovial/deploys/ as YAML files,
tracking accept/complete/fail status with timestamps.
"""

import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEPLOYS_DIR = Path.home() / ".cryovial" / "deploys"


@dataclass
class ServiceConfig:
    """Identity and location of a deployable service.

    Attributes:
        name: Human-readable service name (e.g., "dumpster-backend").
        stack_name: laconic-so deployment directory path.
        repo_dir: Path to the stack repo (cwd for laconic-so commands).
    """

    name: str
    stack_name: str
    repo_dir: str


def _short_id() -> str:
    """Generate a short deploy ID (first 8 chars of uuid4)."""
    return uuid.uuid4().hex[:8]


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class DeployRecord:
    """Record of a deploy attempt, persisted as YAML.

    Written on accept, updated on completion or failure.
    """

    id: str = field(default_factory=_short_id)
    service: str = ""
    image: str = ""
    status: str = "accepted"
    accepted_at: str = field(default_factory=_now)
    completed_at: str = ""
    error: str = ""

    def _path(self) -> Path:
        return DEPLOYS_DIR / f"{self.id}.yml"

    def save(self) -> None:
        """Write record to ~/.cryovial/deploys/<id>.yml."""
        DEPLOYS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "id": self.id,
            "service": self.service,
            "image": self.image,
            "status": self.status,
            "accepted_at": self.accepted_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }
        self._path().write_text(yaml.dump(data, default_flow_style=False))

    def complete(self) -> None:
        self.status = "completed"
        self.completed_at = _now()
        self.save()

    def fail(self, error: str) -> None:
        self.status = "failed"
        self.completed_at = _now()
        self.error = error
        self.save()


def deploy(service_config: ServiceConfig, image: str | None = None) -> None:
    """Deploy a service, optionally with a specific image tag.

    When image is provided, passes --image to laconic-so deployment
    restart so the container is updated to the exact SHA-tagged image
    from CI. When no image is provided, does a plain restart.
    """
    cmd = [
        "laconic-so",
        "deployment",
        "--dir",
        service_config.stack_name,
        "restart",
    ]
    if image:
        cmd.extend(["--image", f"{service_config.name}={image}"])
        log.info("Deploying with image: %s=%s", service_config.name, image)
    else:
        log.info("No image specified, restarting with current image")

    result = subprocess.run(
        cmd,
        cwd=service_config.repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        log.error("Deploy failed (stdout): %s", result.stdout.strip())
        log.error("Deploy failed (stderr): %s", result.stderr.strip())
        result.check_returncode()
