"""凭据保险库适配器（A4-01 §1）：秘密后端 + 分层调度。"""

from butler_engine.vault.backends import MemoryVaultBackend, SecretBackend
from butler_engine.vault.errors import (
    VaultAccessError,
    VaultCredentialMissing,
    VaultError,
    VaultLayerUnavailable,
)
from butler_engine.vault.keychain_macos import KeychainBackend
from butler_engine.vault.layered import LayeredVault

__all__ = [
    "KeychainBackend",
    "LayeredVault",
    "MemoryVaultBackend",
    "SecretBackend",
    "VaultAccessError",
    "VaultCredentialMissing",
    "VaultError",
    "VaultLayerUnavailable",
]
