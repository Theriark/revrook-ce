"""Static checks of the container files.

These do not replace running the stack (merge gate checks 8 and 9); they catch
drift in the settings the plan fixes: port 8080, uid 10001, hashed installs.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_dockerfile_is_a_two_stage_non_root_hashed_build() -> None:
    assert DOCKERFILE.count("FROM python:3.12-slim") == 2
    assert "AS builder" in DOCKERFILE
    assert "pip install --require-hashes --no-deps -r requirements.txt" in DOCKERFILE
    assert "USER 10001:10001" in DOCKERFILE
    assert "EXPOSE 8080" in DOCKERFILE
    assert "HEALTHCHECK" in DOCKERFILE
    assert "/healthz" in DOCKERFILE
    assert "ROLE=all" in DOCKERFILE


def test_dockerfile_never_touches_the_development_lock() -> None:
    assert "requirements-dev" not in DOCKERFILE
    assert "pytest" not in DOCKERFILE


def test_compose_has_web_worker_and_db_on_postgres_16() -> None:
    services = COMPOSE["services"]
    assert set(services) == {"web", "worker", "db"}
    assert services["db"]["image"] == "postgres:16"
    assert services["web"]["ports"] == ["8080:8080"]
    assert services["web"]["environment"]["ROLE"] == "web"
    assert services["worker"]["environment"]["ROLE"] == "worker"
    assert "ports" not in services["worker"]
    assert "ports" not in services["db"]


@pytest.mark.parametrize("service", ["web", "worker"])
def test_app_services_are_read_only_with_tmpfs(service: str) -> None:
    definition = COMPOSE["services"][service]
    assert definition["read_only"] is True
    assert "/tmp" in definition["tmpfs"]
    assert definition["depends_on"]["db"]["condition"] == "service_healthy"


def test_compose_keeps_keys_out_of_the_file() -> None:
    environment = COMPOSE["services"]["web"]["environment"]
    assert environment["SECRET_KEY"].startswith("${SECRET_KEY:?")
    assert environment["FERNET_KEY"].startswith("${FERNET_KEY:?")


def test_worker_does_not_inherit_the_web_health_check() -> None:
    assert COMPOSE["services"]["worker"]["healthcheck"] == {"disable": True}


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
@pytest.mark.parametrize(
    "script", ["scripts/e2e/phase_00.sh", "scripts/check_image_packages.sh"]
)
def test_shell_scripts_parse(script: str) -> None:
    result = subprocess.run(
        ["bash", "-n", str(ROOT / script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
