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


def test_worker_has_its_own_health_check_that_reads_its_command_line() -> None:
    # `docker compose up --wait` rejects a service without a health check, and
    # the web health check (port 8080) does not apply to the worker.
    worker = COMPOSE["services"]["worker"]
    health = worker["healthcheck"]
    assert health.get("disable") is not True
    assert health["test"][0] == "CMD"
    assert "/proc/1/cmdline" in " ".join(health["test"])
    assert "8080" not in " ".join(health["test"])
    assert worker["command"] == ["worker"]
    for key in ("interval", "timeout", "retries", "start_period"):
        assert key in health


def test_no_service_depends_on_a_service_without_a_health_check() -> None:
    services = COMPOSE["services"]
    for definition in services.values():
        for name, condition in definition.get("depends_on", {}).items():
            if condition["condition"] == "service_healthy":
                assert "test" in services[name].get("healthcheck", {}), name


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
@pytest.mark.parametrize(
    "script",
    [
        "scripts/e2e/phase_00.sh",
        "scripts/e2e/phase_05.sh",
        "scripts/e2e/phase_10.sh",
        "scripts/restore_check.sh",
        "scripts/check_image_packages.sh",
    ],
)
def test_shell_scripts_parse(script: str) -> None:
    result = subprocess.run(
        ["bash", "-n", str(ROOT / script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
