"""凭据保险库错误（engine 侧）：语义基类在 core——端口语义归 core（A2-02 §5），
适配器类型继承之，连接器层可以统一捕获（如声明式引擎把缺凭据折算成 NO_AUTH）。"""

from butler_core.accounts.ports import CredentialMissing
from butler_core.shared.errors import DomainError


class VaultError(DomainError):
    """保险库操作失败的基类。"""


class VaultCredentialMissing(VaultError, CredentialMissing):
    """load 申报的 kind 没有入库记录——绝不静默返回空列表。"""


class VaultAccessError(VaultError):
    """秘密后端读写失败（Keychain / 凭据管理器拒绝或环境不可用）。"""


class VaultLayerUnavailable(VaultError):
    """请求的存储层不存在于本装配（如把 AES-GCM 加密库层当默认）。"""
