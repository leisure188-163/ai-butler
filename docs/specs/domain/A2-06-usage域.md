# A2-06 · 用量域（usage）

> 状态：**生效 v1.0（2026-11-14）**　总纲：[A2-01](A2-01-领域模型与动作模型.md)
> 用户词：**流量**（页名级）/ **用量**（域内数据语境）。本域是计量与额度语义的唯一出处。

## 1. 职责与边界

- 管：UsageSample 采集入账、额度三型语义谓词、耗尽预测（forecast_exhaustion）、
  阈值判定（QUOTA_LOW 产出）。
- 不管：凭据事实（accounts）、采集动作的执行（经 execution 域跑 usage.collect）、
  通知发送（L0 通知中心消费事件）。

## 2. 实体与不变量

```
UsageSample：tokens_in / tokens_out / model / ts / source(client|gateway|api)
  ——一律挂 account_id，按账号隔离（is_quota_low 等谓词输入随账号）
额度三型语义谓词（domain 内，端零映射的 core 端落点）：
  is_quota_low / 余额分级 / forecast_exhaustion（耗尽时间预测）
```

不变量：
1. 样本只增不改（时序事实）；写入失败不影响业务主流程（台账语义，A1-02 §6）
2. 阈值谓词只在本域定义——端上/其他域不得复制阈值逻辑
3. 采集样本必须有来源标注（source），无来源样本拒绝入账

## 3. 端口（usage/ports.py）

- `UsageCollectorPort`：连接器侧采集（如实申报支持度；不支持 → 通道 SKIPPED）
- `UsageRepoPort`：用量持久化（SQLite 三表：usage_snapshots / usage_aggregates /
  quota_ledger，DDL 视图 `db/schema.sql`；时序独立表 = R 系列方向，A4-01 §5）

## 4. 用例

| 用例 | 语义 |
|---|---|
| `collect_usage` | 按账号采集 → 样本校验（来源必填）→ 入账 → 触发阈值谓词 → QUOTA_LOW 事件（达阈值时） |

## 5. 事件联动

- `QUOTA_LOW`：severity 按规则映射（A4-01）；事件 payload 携带账号维度，
  支撑 scheduling 域的 threshold 触发器消费。

## 6. 禁止

- ❌ 额度/预测语义写进端或连接器（core 唯一出处）
- ❌ 采集失败静默丢弃（如实上报，红线 5）
- ❌ 非用量数据混入 usage 三表（快照/汇总/额度流水只收用量域事实）
