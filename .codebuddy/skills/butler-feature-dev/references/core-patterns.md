# core 层模式（domain / ports / usecase）

> 证据文件均为真实先例；骨架只列签名级形状。写前先读对应域 A2 分册。

## 0. 目录与依赖铁律

```
butler_core/
  bootstrap.py            # 组装根 build_kit（只认端口协议，零框架依赖）
  shared/                 # errors / events / results / health_level / ids / time
  accounts|execution|usage|health|scheduling/   # 五域互不 import（ADR-002）
    domain.py  ports.py  usecases/<一用例一文件>.py
```

- `domain.py` **只准** import `butler_core.shared`（机检：`scripts/verify_project.py:130-158`）
- core 全包禁框架 import（机检 `check_core_purity`，AST 扫描）
- 跨域复用 = 提升到 `shared/`，不是互相 import

## 1. domain.py 形状

先例：`packages/core/src/butler_core/accounts/domain.py:50-69`

```python
"""<域> 领域模型（A2-0x §n）。"""

@dataclass(frozen=True)
class Credential:
    account_id: str
    kind: str
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise AccountInvalid("account_id 不得为空")
```

要点：
- 实体/值对象一律 `@dataclass(frozen=True)`；校验在 `__post_init__` 显式抛域异常
- 域异常继承 `DomainError`（`shared/errors.py`），随域定义（`domain.py:22-31`）
- 规范 id 由纯函数出产（如 `account_identity`），不做隐式归一
- 敏感值对象覆写 `__repr__ = __str__ = "[REDACTED]"`（`Secret`，`domain.py:129-146`）
- 时钟一律注入：`Callable[[], datetime]`，默认 `shared.time.now_utc`
- 枚举用 `StrEnum`（`shared/results.py:26-40`）；**语义谓词用字典单源**（`results.py:74-82`，端零映射载体）
- 谓词函数出产决策（如 `is_quota_low`、`forecast_exhaustion`），端/server 只消费结果

## 2. ports.py 形状

先例：`packages/core/src/butler_core/accounts/ports.py:18-31, 64-77`

```python
class AccountRepository(ABC):
    """<一句话契约，引 spec 编号>。"""

    @abstractmethod
    def get(self, account_id: str) -> Account | None: ...


class CredentialPool(Protocol):
    """实现必须让任何 acquire 都有审计留痕；缺凭据显式抛，不静默给空。"""

    def acquire(self, *, account_id: str, purpose: str) -> ...: ...
```

- ABC（仓储类）与 Protocol（能力类）混用；方法体一律 `...`
- **契约写类 docstring**（不变量、失败语义、引 spec/裁决编号），方法 docstring 一句话语义
- 端口语义错误类（如 `CredentialMissing`）定义在同文件
- 端口随域走，禁止新建全库单一 ports.py

## 3. usecase 形状与错误处理三段语义

一用例一文件，`<域>/usecases/<动词>.py`。模块 docstring 先写语义契约，再代码。

```python
@dataclass
class RecordUsageSample:
    """<一句话>。"""

    store: UsageStore                                  # 端口注入
    audit: MeterAuditSink                              # 用例内可声明局部 Protocol
    clock: Callable[[], datetime] = field(default=now_utc)

    def record(self, *, account_id: str, model: str, ...) -> bool:
        ...  # 干净路径
```

错误处理三段语义（红线 5 的正面写法）：

| 输入类别 | 处理 | 先例 |
|---|---|---|
| 非法输入/配置（调用方 bug） | 显式抛 `DomainError` 子类，**不吞** | `record_sample.py:1-12`（负 token → UsageInvalid） |
| 侧效应失败（存储/外部写不进） | 审计留痕 + 返回 False 或 outcome.error，**不打断主流程**（台账语义） | `record_sample.py:67-76`；`execute_action.py` 落账 FAILED |
| 意外异常 | 落账后**原样 re-raise**（不吞红线 5） | `execute_action.py:170-179` |

其他先例：
- `accounts/usecases/register_account.py:22-53`：幂等回放（同身份重复停靠不覆盖不改号）+ 形状冲突显式抛
- `execution/usecases/execute_action.py:76-181`：请求校验先行 → 幂等命中回放原 Run → 显式拒绝（UnsupportedAction/DryRunNotSupported）→ 终态统一 `_terminate` 落账 + 发事件

## 4. 模型分层规约（R7，源自六边形规约）

| 手册词汇 | 本架构落点 |
|---|---|
| DO（数据对象） | engine 行对象、引擎原始返回 |
| DTO / AO | core 用例入参与返回（frozen dataclass） |
| VO / 出参 | server `response_model`（`*Out` 后缀）、web 契约类型 |

禁止把 DO 直接透传到端——出站形状必须显式声明 `response_model`。

## 5. 测试策略（R8）

core 用例纯 pytest、毫秒级、零 mock IO（Fake 端口即可）；非法输入 `pytest.raises` + 表驱动边界断言。详见 `tests-and-gates.md`。
