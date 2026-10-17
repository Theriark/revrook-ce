import dataclasses
from pathlib import Path

import pytest

from app.settings import SettingsError, get_settings, load_settings

ROOT = Path(__file__).resolve().parent.parent


def test_minimal_environment_uses_documented_defaults(env: dict[str, str]) -> None:
    settings = load_settings(env)
    assert settings.role == "all"
    assert settings.base_url == "http://localhost:8080"
    assert settings.evidence_dir == "/data/evidence"
    assert settings.raw_retention_days == 0
    assert settings.pack_retention_months == 25
    assert settings.import_max_bytes == 20_971_520
    assert settings.import_max_rows == 200_000
    assert settings.log_level == "info"
    assert settings.smtp_port == 587
    assert settings.metrics_token is None
    assert settings.heartbeat_url is None
    assert settings.dns_resolver is None


def test_startup_fails_without_secret_key_and_fernet_key(env: dict[str, str]) -> None:
    del env["SECRET_KEY"]
    del env["FERNET_KEY"]
    with pytest.raises(SettingsError) as raised:
        load_settings(env)
    message = str(raised.value)
    assert "SECRET_KEY is required" in message
    assert "FERNET_KEY is required" in message


@pytest.mark.parametrize("name", ["SECRET_KEY", "FERNET_KEY", "DATABASE_URL"])
@pytest.mark.parametrize("blank", [None, "", "   "])
def test_each_required_variable_is_enforced(
    env: dict[str, str], name: str, blank: str | None
) -> None:
    if blank is None:
        del env[name]
    else:
        env[name] = blank
    with pytest.raises(SettingsError, match=f"{name} is required"):
        load_settings(env)


@pytest.mark.parametrize(
    ("name", "value", "fragment"),
    [
        ("SECRET_KEY", "short", "at least 16 characters"),
        ("FERNET_KEY", "not-a-key", "32-byte key"),
        ("DATABASE_URL", "postgresql://u:p@host/db", "must start with"),
        ("BASE_URL", "ftp://example", "http:// or https://"),
        ("ROLE", "bogus", "ROLE must be one of"),
        ("LOG_LEVEL", "loud", "LOG_LEVEL must be one of"),
        ("RAW_RETENTION_DAYS", "36", "between 0 and 35"),
        ("RAW_RETENTION_DAYS", "abc", "must be an integer"),
        ("PACK_RETENTION_MONTHS", "0", "PACK_RETENTION_MONTHS must be between"),
        ("IMPORT_MAX_BYTES", "0", "IMPORT_MAX_BYTES must be between"),
        ("IMPORT_MAX_ROWS", "-1", "IMPORT_MAX_ROWS must be between"),
        ("SMTP_PORT", "70000", "SMTP_PORT must be between"),
    ],
)
def test_invalid_values_are_rejected(
    env: dict[str, str], name: str, value: str, fragment: str
) -> None:
    env[name] = value
    with pytest.raises(SettingsError, match=fragment):
        load_settings(env)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SECRET_KEY", "short-secret"),
        ("FERNET_KEY", "sentinel-fernet-value"),
        ("DATABASE_URL", "postgresql://user:hunter2@host/db"),
    ],
)
def test_error_messages_never_echo_values(
    env: dict[str, str], name: str, value: str
) -> None:
    env[name] = value
    with pytest.raises(SettingsError) as raised:
        load_settings(env)
    assert value not in str(raised.value)
    assert "hunter2" not in str(raised.value)


def test_boundary_values_are_accepted(env: dict[str, str]) -> None:
    env["RAW_RETENTION_DAYS"] = "35"
    env["SMTP_PORT"] = "65535"
    settings = load_settings(env)
    assert settings.raw_retention_days == 35
    assert settings.smtp_port == 65_535


def test_overrides_are_read_and_normalised(env: dict[str, str]) -> None:
    env.update(
        {
            "ROLE": "Worker",
            "LOG_LEVEL": "DEBUG",
            "BASE_URL": "https://revrook.example.test",
            "EVIDENCE_DIR": "/tmp/evidence",
            "METRICS_TOKEN": "metrics-token-value",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "2525",
            "SMTP_USER": "mailer",
            "SMTP_PASSWORD": "mailer-password",
            "SMTP_FROM": "revrook@example.test",
            "HEARTBEAT_URL": "https://heartbeat.example.test/ping",
            "DNS_RESOLVER": "https://dns.example.test/dns-query",
        }
    )
    settings = load_settings(env)
    assert settings.role == "worker"
    assert settings.log_level == "debug"
    assert settings.base_url == "https://revrook.example.test"
    assert settings.evidence_dir == "/tmp/evidence"
    assert settings.metrics_token == "metrics-token-value"
    assert settings.smtp_host == "smtp.example.test"
    assert settings.smtp_port == 2525
    assert settings.smtp_user == "mailer"
    assert settings.smtp_from == "revrook@example.test"
    assert settings.heartbeat_url == "https://heartbeat.example.test/ping"
    assert settings.dns_resolver == "https://dns.example.test/dns-query"


def test_empty_optional_values_count_as_unset(env: dict[str, str]) -> None:
    env.update({"ROLE": "", "METRICS_TOKEN": "", "SMTP_PORT": "", "BASE_URL": ""})
    settings = load_settings(env)
    assert settings.role == "all"
    assert settings.metrics_token is None
    assert settings.smtp_port == 587
    assert settings.base_url == "http://localhost:8080"


def test_secrets_stay_out_of_repr_and_settings_are_frozen(env: dict[str, str]) -> None:
    env["METRICS_TOKEN"] = "metrics-token-value"
    env["SMTP_PASSWORD"] = "mailer-password"
    settings = load_settings(env)
    text = repr(settings)
    for secret in (
        env["SECRET_KEY"],
        env["FERNET_KEY"],
        env["DATABASE_URL"],
        "metrics-token-value",
        "mailer-password",
    ):
        assert secret not in text
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.role = "web"  # type: ignore[misc]


def test_get_settings_reads_the_process_environment_once(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
        monkeypatch.delenv("SECRET_KEY")
        assert get_settings().secret_key == env["SECRET_KEY"]
        get_settings.cache_clear()
        with pytest.raises(SettingsError, match="SECRET_KEY is required"):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_env_example_is_a_valid_throwaway_configuration(env: dict[str, str]) -> None:
    values: dict[str, str] = {"DATABASE_URL": env["DATABASE_URL"]}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            name, _, value = text.partition("=")
            values[name] = value
    settings = load_settings(values)
    assert settings.secret_key.startswith("local-dev-only")
