# A2-12 · 执行域（execution）

> 状态：**生效 v1.0（2026-11-14）**　总纲：[A2-01](A2-01-领域模型与动作模型.md)
> 用户词：**领取**（Claim）。本域是"管家替你干活"的核心：动作定义、执行记录、幂等。

## 1. 职责与边界

- 管：Action 定义、Run 生命周期、幂等键、时间预算、结果词汇的消费出口（Result）。
- 不管：何时触发（scheduling 域）、执行所需的凭据事实（accounts 域端口读取）、
  连接器怎么做（A2-02，适配器不做语义决策）。

## 2. 实体与不变量

```
Action = (kind, target, params)
  target = 应用 + 账号编址（多账号，A2-01 §2）
Run = id / action / account_id / idempotency_key / started_at / budget
  → Result(status ∈ 七字面量, kind 谓词, evidence[], repair_hint?)
```

不变量：
1. **幂等键 = (kind, account_id, 签到窗口)**——同键重复触发必须命中回放，
   绝不二次领取（继承旧系统已验证语义，测试钉死）
2. 时间预算超限 → 立即停止并如实上报 FAILED/部分证据，不静默截断
3. `dry_run=True` 只报告不领取；Connector 申报不支持 dry_run → 用例层拒绝，
   **绝不静默降级**（红线 5 的用例级落点）

## 3. 端口（execution/ports.py）

- `ProvisionPort`：capabilities() 如实申报（dry_run / 多账户 / 幂等窗口）+
  run(ProvisionRequest) → 结构化 RunResult（不返回退出码）
- `RunRepoPort`：Run 记录持久化与幂等回放查询

## 4. 用例

| 用例 | 语义 |
|---|---|
| `execute_action` | 校验能力申报 → 幂等查询 → 时间预算内执行 → 结构化 Result + RUN_FINISHED 事件 |

## 5. 事件联动

- Run 终态发 `RUN_FINISHED`（通知/台账/统计统一入口）；成功 = silent，
  `is_attention` 才可见（A2-01 §5）。

## 6. 禁止

- ❌ kind 枚举在 core 外扩展（新 kind 走 ADR 立项）
- ❌ 触发调度逻辑混入本域（属 scheduling）
- ❌ 适配器内维护结果映射表或解析日志文本定语义（端零映射红线 2）
