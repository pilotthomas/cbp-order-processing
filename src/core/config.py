"""App settings from the environment, with secrets from Key Vault."""

from __future__ import annotations

import os

from src.core.keyvault import get_secret

# Key Vault secret names. An environment variable with the same setting wins when it is set.
DB_HOST_SECRET_DEFAULT = "cbp-db-hostname"
DB_NAME_SECRET_DEFAULT = "cbp-db-name"
DB_USERNAME_SECRET_DEFAULT = "cbp-db-user"
DB_PASSWORD_SECRET_DEFAULT = "cbp-db-password"
DB_ODBC_DRIVER_SECRET_DEFAULT = "cbp-odbc-driver"
DB_TRUSTED_CONNECTION_SECRET_DEFAULT = "cbp-db-trusted-connection"
DB_TRUST_SERVER_CERTIFICATE_SECRET_DEFAULT = "cbp-trust-server-certificate"
CBP_CLIENT_ID_SECRET_DEFAULT = "cbp-client-id"
CBP_CLIENT_SECRET_SECRET_DEFAULT = "cbp-client-secret"
CBP_SUBSCRIPTION_KEY_SECRET_DEFAULT = "cbp-subscription-key"
CBP_RESOURCE_SECRET_DEFAULT = "cbp-resource"
ROSETTA_HOST_SECRET_DEFAULT = "cbp-rosetta-api-host"
ROSETTA_PORT_SECRET_DEFAULT = "cbp-rosetta-api-port"
ROSETTA_TIMEOUT_SECRET_DEFAULT = "cbp-rosetta-timeout-seconds"
ROSETTA_SECURITY_KEY_SECRET_DEFAULT = "cbp-rosetta-api-security-key"
ROSETTA_FUNCTION_SECRET_DEFAULT = "cbp-rosetta-function-create"

ROSETTA_FUNCTION_DEFAULT = "CreateOrder"
ROSETTA_PORT_DEFAULT = 55555
ROSETTA_TIMEOUT_DEFAULT = 30.0
DEFAULT_TIME_ZONE = "America/Chicago"

_credentials: dict[str, str] = {}


def reset_credentials() -> None:
    """Clear cached SQL / Rosetta secrets (for tests)."""
    _credentials.clear()


def _use_trusted_connection() -> bool:
    return _setting(
        "DB_TRUSTED_CONNECTION",
        DB_TRUSTED_CONNECTION_SECRET_DEFAULT,
        default="",
        secret_env="DB_TRUSTED_CONNECTION_SECRET_NAME",
    ).lower() in {"yes", "true", "1"}


def _has_env_db_credentials() -> bool:
    return bool(os.getenv("DB_USER", "").strip() and os.getenv("DB_PASSWORD", "").strip())


def _has_setting_or_vault(env_name: str) -> bool:
    return bool(os.getenv(env_name, "").strip() or os.getenv("KEY_VAULT_URL", "").strip())


def is_db_configured() -> bool:
    if not all(_has_setting_or_vault(name) for name in ("DB_HOST", "DB_NAME", "DB_ODBC_DRIVER")):
        return False
    if _use_trusted_connection():
        return True
    return _has_env_db_credentials() or bool(os.getenv("KEY_VAULT_URL", "").strip())


def get_db_host() -> str:
    return _setting("DB_HOST", DB_HOST_SECRET_DEFAULT, secret_env="DB_HOST_SECRET_NAME")


def get_db_name() -> str:
    return _setting("DB_NAME", DB_NAME_SECRET_DEFAULT, secret_env="DB_NAME_SECRET_NAME")


def get_primary_host() -> str | None:
    host = _setting("DB_HOST", DB_HOST_SECRET_DEFAULT, default="", secret_env="DB_HOST_SECRET_NAME")
    return host or None


def get_time_zone_name() -> str:
    """IANA zone for every date this job reads or writes. Default America/Chicago."""
    return os.getenv("TIME_ZONE", "").strip() or DEFAULT_TIME_ZONE


def get_rosetta_host() -> str | None:
    host = _setting(
        "ROSETTA_HOST",
        ROSETTA_HOST_SECRET_DEFAULT,
        secret_env="ROSETTA_HOST_SECRET_NAME",
    )
    return host or None


def _secret_name(env_name: str, default: str) -> str:
    return os.getenv(env_name, "").strip() or default


def _setting(
    env_name: str,
    default_secret: str,
    default: str | None = None,
    secret_env: str | None = None,
) -> str:
    """Environment value, otherwise the Key Vault secret. A default skips the vault."""
    from_env = os.getenv(env_name, "").strip()
    if from_env:
        return from_env
    cached = _credentials.get(env_name)
    if cached is not None:
        return cached
    if not os.getenv("KEY_VAULT_URL", "").strip():
        if default is not None:
            return default
        raise RuntimeError(
            f"{env_name} is not set and KEY_VAULT_URL is required to read {default_secret!r}."
        )
    name = _secret_name(secret_env, default_secret) if secret_env else default_secret
    value = get_secret(name).strip()
    if not value:
        if default is not None:
            return default
        raise RuntimeError(f"Key Vault secret {name!r} is empty")
    _credentials[env_name] = value
    return value


def _credential(env_name: str, secret_env: str, default_secret: str) -> str:
    return _setting(env_name, default_secret, secret_env=secret_env)


def get_db_username() -> str:
    return _credential("DB_USER", "DB_USER_SECRET_NAME", DB_USERNAME_SECRET_DEFAULT)


def get_db_password() -> str:
    return _credential("DB_PASSWORD", "DB_PASSWORD_SECRET_NAME", DB_PASSWORD_SECRET_DEFAULT)


def get_rosetta_security_key() -> str:
    return _setting(
        "ROSETTA_SECURITY_KEY",
        ROSETTA_SECURITY_KEY_SECRET_DEFAULT,
        secret_env="ROSETTA_SECURITY_KEY_SECRET_NAME",
    )


def _odbc_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def get_pyodbc_connection_string() -> str:
    """ODBC connection string. SQL login comes from env or Key Vault."""
    if not is_db_configured():
        raise RuntimeError(
            "Database is not configured. Set DB_HOST, DB_NAME, and DB_ODBC_DRIVER, "
            "or set KEY_VAULT_URL so cbp-db-hostname, cbp-db-name, and cbp-odbc-driver can be read."
        )
    host = get_db_host()
    database = get_db_name()
    port = os.getenv("DB_PORT", "").strip()
    driver = _setting(
        "DB_ODBC_DRIVER",
        DB_ODBC_DRIVER_SECRET_DEFAULT,
        secret_env="DB_ODBC_DRIVER_SECRET_NAME",
    )
    trust = _setting(
        "DB_TRUST_SERVER_CERTIFICATE",
        DB_TRUST_SERVER_CERTIFICATE_SECRET_DEFAULT,
        default="yes",
        secret_env="DB_TRUST_SERVER_CERTIFICATE_SECRET_NAME",
    ) or "yes"
    # No port lets a local default instance connect over shared memory.
    server = f"{host},{port}" if port else host
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        f"TrustServerCertificate={trust}",
    ]
    if _use_trusted_connection():
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={_odbc_value(get_db_username())}")
        parts.append(f"PWD={_odbc_value(get_db_password())}")
    return ";".join(parts)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


class Settings:
    """Rosetta settings. Secrets resolve on first use."""

    @property
    def app_name(self) -> str:
        return os.getenv("APP_NAME", "").strip() or "CBP Order API"

    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "").strip() or "INFO"

    @property
    def time_zone(self) -> str:
        return get_time_zone_name()

    @property
    def rosetta_host(self) -> str:
        return get_rosetta_host() or ""

    @property
    def rosetta_port(self) -> int:
        raw = _setting(
            "ROSETTA_PORT",
            ROSETTA_PORT_SECRET_DEFAULT,
            default=str(ROSETTA_PORT_DEFAULT),
            secret_env="ROSETTA_PORT_SECRET_NAME",
        )
        return int(raw or ROSETTA_PORT_DEFAULT)

    @property
    def rosetta_timeout_seconds(self) -> float:
        raw = _setting(
            "ROSETTA_TIMEOUT_SECONDS",
            ROSETTA_TIMEOUT_SECRET_DEFAULT,
            default=str(ROSETTA_TIMEOUT_DEFAULT),
            secret_env="ROSETTA_TIMEOUT_SECRET_NAME",
        )
        return float(raw or ROSETTA_TIMEOUT_DEFAULT)

    @property
    def rosetta_security_key(self) -> str:
        return get_rosetta_security_key()

    @property
    def rosetta_function(self) -> str:
        return _setting(
            "ROSETTA_FUNCTION",
            ROSETTA_FUNCTION_SECRET_DEFAULT,
            default=ROSETTA_FUNCTION_DEFAULT,
            secret_env="ROSETTA_FUNCTION_SECRET_NAME",
        ) or ROSETTA_FUNCTION_DEFAULT

    @property
    def batch_size(self) -> int | None:
        """Orders per run. A blank BATCH_SIZE selects every eligible row."""
        raw = os.getenv("BATCH_SIZE", "").strip()
        if not raw:
            return None
        size = int(raw)
        return size if size > 0 else None

    @property
    def cbp_token_url(self) -> str:
        return os.getenv("CBP_TOKEN_URL", "").strip()

    @property
    def cbp_client_id(self) -> str:
        return _setting(
            "CBP_CLIENT_ID",
            CBP_CLIENT_ID_SECRET_DEFAULT,
            secret_env="CBP_CLIENT_ID_SECRET_NAME",
        )

    @property
    def cbp_client_secret(self) -> str:
        return _setting(
            "CBP_CLIENT_SECRET",
            CBP_CLIENT_SECRET_SECRET_DEFAULT,
            secret_env="CBP_CLIENT_SECRET_SECRET_NAME",
        )

    @property
    def cbp_resource(self) -> str:
        return _setting(
            "CBP_RESOURCE",
            CBP_RESOURCE_SECRET_DEFAULT,
            secret_env="CBP_RESOURCE_SECRET_NAME",
        )

    @property
    def cbp_order_list_url(self) -> str:
        return os.getenv("CBP_ORDER_LIST_URL", "").strip()

    @property
    def cbp_order_detail_url(self) -> str:
        return os.getenv("CBP_ORDER_DETAIL_URL", "").strip()

    @property
    def cbp_subscription_key(self) -> str:
        return _setting(
            "CBP_SUBSCRIPTION_KEY",
            CBP_SUBSCRIPTION_KEY_SECRET_DEFAULT,
            secret_env="CBP_SUBSCRIPTION_KEY_SECRET_NAME",
        )

    @property
    def cbp_detail_concurrency(self) -> int:
        """Parallel Get Order calls. The list API has no pages, so this caps load."""
        size = _env_int("CBP_DETAIL_CONCURRENCY", 4)
        return size if size > 0 else 4

    @property
    def cbp_list_status(self) -> str:
        return os.getenv("CBP_LIST_STATUS", "").strip() or "UNACKNOWLEDGED"

    @property
    def cbp_base_site_id(self) -> str:
        return os.getenv("CBP_BASE_SITE_ID", "").strip() or "businessPoint_NA"

    @property
    def cbp_from_date(self) -> str:
        """List Orders fromDate. CBP_FROM_DATE defaults to 10-22-2025."""
        return os.getenv("CBP_FROM_DATE", "").strip() or "10-22-2025"

    @property
    def cbp_to_date(self) -> str:
        """List Orders toDate. CBP_TO_DATE defaults to 10-23-2026."""
        return os.getenv("CBP_TO_DATE", "").strip() or "10-23-2026"

    @property
    def cbp_token_refresh_skew_seconds(self) -> int:
        """Refresh the CBP token this many seconds before it expires."""
        skew = _env_int("CBP_TOKEN_REFRESH_SKEW_SECONDS", 300)
        return skew if skew >= 0 else 300


def get_settings() -> Settings:
    return Settings()
