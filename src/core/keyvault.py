"""Azure Key Vault secrets via Managed Identity (DefaultAzureCredential)."""

from __future__ import annotations

import os

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from src.core.logger import log_exception, logger

_client: SecretClient | None = None


def reset_keyvault_client() -> None:
    """Clear cached client (for tests)."""
    global _client
    _client = None


def require_key_vault_url() -> str:
    """Fail fast when Key Vault URL is not configured."""
    vault_url = os.getenv("KEY_VAULT_URL", "").strip()
    if not vault_url:
        logger.error("require_key_vault_url: KEY_VAULT_URL is not configured")
        raise RuntimeError(
            "KEY_VAULT_URL is required. "
            "Set it in local.settings.json or Function App settings."
        )
    return vault_url


def _get_client() -> SecretClient:
    global _client
    if _client is None:
        vault_url = require_key_vault_url()
        credential = DefaultAzureCredential()
        _client = SecretClient(vault_url=vault_url, credential=credential)
    return _client


def get_secret(secret_name: str) -> str:
    """Read a secret value from Key Vault."""
    try:
        return _get_client().get_secret(secret_name).value or ""
    except Exception as exc:
        log_exception(f"get_secret: failed (name={secret_name})", exc=exc)
        raise
