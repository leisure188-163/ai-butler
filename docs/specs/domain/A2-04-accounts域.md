# A2-04 · 账户域（accounts）

> 状态：**生效 v1.0（2026-11-14）**　总纲：[A2-01](A2-01-领域模型与动作模型.md) ·
> 结构：[A1-05 §2](../architecture/A1-05-按业务域重写总设计.md)
> 用户词：**账户**（Account）/ **导入**（Import）。本域是全部业务标识的锚点。

## 1. 职责与边界

- 管：Provider、Account 集合（多账号，ADR-010）、Credential、Entitlement、Session、
  账户注册与凭据导入入口、vault 端口（预警窗常量随域）。
- 不管：执行动作（execution）、用量计算（usage）、健康评级规则（health）——
  本域只提供账户事实，评级与动作由对应域消费。

## 2. 实体与不变量

```
Provider：Connector 的产品级身份（id + display + capabilities 申报源）
Account（聚合根）：
  identity = (provider_id, account_key)；account_key 缺省 "main"
  同一 Provider 下 account_key 唯一；删除账户 = 软删除（台账/审计保留 account_id）
Credential：kind(ss_aes/cookie/oauth/api-key) / 密文 / 有效期 / 轮换历史
  ——凭据必须绑定 account，禁止按应用共享（ADR-010 §5）
Entitlement：余额 / 连签 / 上次领取窗口（按账号隔离）
Session：存储位置 / 可迁移级别(local|inject|server)
```

不变量：
1. account_id 是全系统外键——Run/Event/Sample 一律挂它
2. 凭据明文永不离开 vault 端口背后（core 只见句柄与元数据）
3. `(provider, account_key)` 缺省落位规则：存量单账号数据迁移时
   account_key = "main"，零信息丢失（迁移测试钉死，A1-05 §5 P4）

## 3. 端口（accounts/ports.py）

- `VaultPort`：凭据存取/解锁（engine 实现；本地凭据解锁链，承袭 M1 收敛裁决 ADR-006）
- `SessionSourcePort`：本机会话/凭据扫描与导入（dock/浏览器通道的数据面）
- `AccountRepoPort`：账户集合的持久化（Repository 接口隔离，A1-02 §6）

## 4. 用例

| 用例 | 语义 |
|---|---|
| `register_account` | 建立 Provider 下账户并落库；`(provider, account_key)` 冲突 → 显式拒绝 |
| 导入多账号 | SessionSourcePort 枚举本机多 profile/多开，逐账号入库（ADR-010 §3；连接器侧逐家取证随 P5 落地，见 A2-02 §5 沙箱） |

## 5. 事件联动

- 凭据到期/将到期事件（CREDENTIAL_EXPIRING / CREDENTIAL_EXPIRED）由 health 域
  扫描产出，事件源头是本域的凭据事实；severity 与通知口径见 A4-01。

## 6. 禁止

- ❌ 账户状态/健康分级逻辑写进本域（那是 health 域的）
- ❌ UI 导航出现 Provider（实现细节下沉）
- ❌ 凭据形状/解密逻辑散出 vault 端口
