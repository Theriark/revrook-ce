"""Runtime settings, read once from the environment (decision D3)."""

import base64
import binascii
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache

ROLES = ("web", "worker", "all")
LOG_LEVELS = ("critical", "error", "warning", "info", "debug")
DATABASE_URL_PREFIX = "postgresql+asyncpg://"
MIN_SECRET_KEY_LENGTH = 16


class SettingsError(ValueError):
    """The environment does not describe a valid configuration.

    Messages name variables and never include their values.
    """


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    secret_key: str = field(repr=False)
    fernet_key: str = field(repr=False)
    base_url: str = "http://localhost:8080"
    role: str = "all"
    evidence_dir: str = "/data/evidence"
    raw_retention_days: int = 0
    pack_retention_months: int = 25
    import_max_bytes: int = 20_971_520
    import_max_rows: int = 200_000
    log_level: str = "info"
    metrics_token: str | None = field(default=None, repr=False)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = field(default=None, repr=False)
    smtp_from: str | None = None
    heartbeat_url: str | None = None
    dns_resolver: str | None = None


def _optional(env: Mapping[str, str], name: str) -> str | None:
    """Return the stripped value, or None when it is missing or empty."""
    value = env.get(name, "").strip()
    return value or None


def _integer(
    env: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
    errors: list[str],
) -> int:
    raw = _optional(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{name} must be an integer")
        return default
    if not minimum <= value <= maximum:
        errors.append(f"{name} must be between {minimum} and {maximum}")
        return default
    return value


def _choice(
    env: Mapping[str, str],
    name: str,
    default: str,
    choices: tuple[str, ...],
    errors: list[str],
) -> str:
    raw = _optional(env, name)
    if raw is None:
        return default
    value = raw.lower()
    if value not in choices:
        errors.append(f"{name} must be one of: {', '.join(choices)}")
        return default
    return value


def _is_fernet_key(value: str) -> bool:
    """A Fernet key is 32 bytes encoded as URL-safe base64."""
    try:
        return len(base64.urlsafe_b64decode(value.encode())) == 32
    except (binascii.Error, ValueError):
        return False


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from env (default: the process environment).

    Raises SettingsError listing every problem found, so one start attempt
    reports all of them.
    """
    source = os.environ if env is None else env
    errors: list[str] = []

    secret_key = _optional(source, "SECRET_KEY")
    if secret_key is None:
        errors.append("SECRET_KEY is required")
    elif len(secret_key) < MIN_SECRET_KEY_LENGTH:
        errors.append(f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters")

    fernet_key = _optional(source, "FERNET_KEY")
    if fernet_key is None:
        errors.append("FERNET_KEY is required")
    elif not _is_fernet_key(fernet_key):
        errors.append("FERNET_KEY must be a URL-safe base64 encoded 32-byte key")

    database_url = _optional(source, "DATABASE_URL")
    if database_url is None:
        errors.append("DATABASE_URL is required")
    elif not database_url.startswith(DATABASE_URL_PREFIX):
        errors.append(f"DATABASE_URL must start with {DATABASE_URL_PREFIX}")

    base_url = _optional(source, "BASE_URL") or Settings.base_url
    if not base_url.startswith(("http://", "https://")):
        errors.append("BASE_URL must start with http:// or https://")

    role = _choice(source, "ROLE", Settings.role, ROLES, errors)
    log_level = _choice(source, "LOG_LEVEL", Settings.log_level, LOG_LEVELS, errors)
    raw_retention_days = _integer(source, "RAW_RETENTION_DAYS", 0, 0, 35, errors)
    pack_retention_months = _integer(source, "PACK_RETENTION_MONTHS", 25, 1, 120, errors)
    import_max_bytes = _integer(
        source, "IMPORT_MAX_BYTES", 20_971_520, 1, 1_073_741_824, errors
    )
    import_max_rows = _integer(source, "IMPORT_MAX_ROWS", 200_000, 1, 10_000_000, errors)
    smtp_port = _integer(source, "SMTP_PORT", 587, 1, 65_535, errors)

    if errors:
        raise SettingsError("invalid configuration: " + "; ".join(errors))

    return Settings(
        database_url=database_url or "",
        secret_key=secret_key or "",
        fernet_key=fernet_key or "",
        base_url=base_url,
        role=role,
        evidence_dir=_optional(source, "EVIDENCE_DIR") or Settings.evidence_dir,
        raw_retention_days=raw_retention_days,
        pack_retention_months=pack_retention_months,
        import_max_bytes=import_max_bytes,
        import_max_rows=import_max_rows,
        log_level=log_level,
        metrics_token=_optional(source, "METRICS_TOKEN"),
        smtp_host=_optional(source, "SMTP_HOST"),
        smtp_port=smtp_port,
        smtp_user=_optional(source, "SMTP_USER"),
        smtp_password=_optional(source, "SMTP_PASSWORD"),
        smtp_from=_optional(source, "SMTP_FROM"),
        heartbeat_url=_optional(source, "HEARTBEAT_URL"),
        dns_resolver=_optional(source, "DNS_RESOLVER"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings; the first call validates the environment."""
    return load_settings()
