# A2-14 · 健康域（health）

> 状态：**生效 v1.0（2026-11-14）**　总纲：[A2-01](A2-01-领域模型与动作模型.md)
> 用户词：**体检**（Health check）。本域是账户/凭据健康语义的唯一出处。

## 1. 职责与边界

- 管：健康分级、风险规则、凭据到期扫描（含预警窗）、`ACCOUNT_HEALTH_CHANGED` 产出。
- 不管：凭据本身（accounts 域事实）、修复动作的执行（经 execution 域跑 health.check）、
  到期提醒的推送（L0 通知中心）。

## 2. 实体与不变量

```
HealthGrade：账户健康分级（正常 / 注意 / 异常，承袭 health.py 分级规则）
风险规则：凭据预警窗（vault.py 常量随域迁入 shared 常量口径）、
  到期 N 天 → CREDENTIAL_EXPIRING；过期 → CREDENTIAL_EXPIRED
```

不变量：
1. 健康评级是**纯函数**：输入凭据/账户事实，输出分级——不做 IO、不发事件之外的动作
2. 分级规则只在本域定义，端上只消费结果（端零映射）
3. 每次评级结果可解释（携带触发规则），支撑"待处理 → 一键修复"的 repair_hint

## 3. 端口（health/ports.py）

- `HealthProbePort`：连接器侧探针（health.check 能力的数据面；网页会话通道
  探针见 A2-03）
- `HealthRepoPort`：评级历史持久化（支撑趋势与去抖）

## 4. 用例

| 用例 | 语义 |
|---|---|
| `health_scan`（ScanCredentialExpiry） | 扫描凭据有效期 → 预警窗判定 → 到期事件 |
| `assess_account_health` | 汇总凭据/最近 Run 结果 → 分级 → `ACCOUNT_HEALTH_CHANGED`（变化时） |

## 5. 事件联动

- `CREDENTIAL_EXPIRING` / `CREDENTIAL_EXPIRED` / `ACCOUNT_HEALTH_CHANGED`；
  到期扫描的定时发起由 scheduling 域 cron 触发器驱动（本域只提供扫描用例）。

## 6. 禁止

- ❌ 健康分级逻辑写进端/连接器（连接器只如实上报探针原始结果）
- ❌ 评级规则复制到通知中心或 UI（A4-01 只消费事件）
- ❌ 扫描失败静默视为健康（如实上报，红线 5）
