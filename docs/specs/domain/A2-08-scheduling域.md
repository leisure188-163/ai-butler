# A2-08 · 调度域（scheduling）

> 状态：**生效 v1.0（2026-11-14）**　总纲：[A2-01](A2-01-领域模型与动作模型.md)
> 用户词：**时间表**（Schedule）。本域回答"什么时候干什么"。

## 1. 职责与边界

- 管：Trigger 三型（cron / event / threshold）、调度窗口（签到窗口等）、
  待办队列（ListPending 的领域语义）。
- 不管：动作怎么执行（execution 域）、额度阈值怎么算（usage 域谓词，本域只消费）、
  系统级定时任务的注册实现（engine 调度器 + schtasks/launchd/cron 兜底）。

## 2. 实体与不变量

```
Trigger：
  cron       进程内调度器默认通道；系统级定时任务为兜底触发器（A2-01 §4）
  event      事件总线驱动（如 CREDENTIAL_EXPIRED → health.check）
  threshold  阈值 watcher（如 QUOTA_LOW → 通知/规则引擎）
窗口（Window）：签到/领取窗口判定；幂等键的时间维度来源（A2-05 §2）
待办（Pending）：到期待办 = 窗口未跑 + is_attention 结果 + 即将到期凭据，
  聚合口径与 UI 角标一致（A1-03 §4）
```

不变量：
1. **触发器只负责"发起 Run"**，所有业务判断在 core 用例层（A2-01 §4）
2. 窗口判定只在本域定义——幂等键里的"窗口"一律由本域计算后传入 execution
3. 同一 (kind, target, account) 只呈现**最新一条** Run 的结果：最新是 attention
   才进待办；最新已恢复（非 attention）时，旧的历史失败自动让位——修好后待办
   必须消失（ADR-015）
4. **健康闸门（ADR-015）**：触发前读账户健康级别，`invalid` / `expired` /
   `risk` 跳过自动触发；同一 (target, account, window) 只记一条跳过日志。
   这是**投递闸门**（不再打无效上游），不是结果分类——健康级别仍只由 health 域出产。
   手动重试（用户在待办里点「我已登录，立即重试」）**不受闸门限制**，成功后
   下一班次自动恢复。`invalid/expired` 的本地凭据副本已由 health 域自动撤销
   （ADR-015），撤销后重试前必须先重新停靠读取客户端新凭据。

## 3. 端口（scheduling/ports.py）

- `SchedulerPort`：注册/取消定时触发（engine 实现）
- `TriggerRepoPort`：触发器与窗口配置持久化

## 4. 用例

| 用例 | 语义 |
|---|---|
| `list_pending` | 汇总窗口未跑 + 待处理结果 + 即将到期 → 待办队列（UI 待办栏与角标的唯一数据源） |

## 5. 事件联动

- event/threshold 触发器消费 shared 事件（CREDENTIAL_EXPIRED / QUOTA_LOW /
  ACCOUNT_HEALTH_CHANGED）并发起对应 Action；本域自身不产出新事件类型。

## 6. 禁止

- ❌ 业务判断写进触发器（只发起 Run）
- ❌ 窗口/幂等时间维度在 execution 或端上另行计算
- ❌ 调度逻辑散进 server 路由层（server 只触发用例）
