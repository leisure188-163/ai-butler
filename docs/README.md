# docs · 文档导航

> kabao 的 docs 是一个有标准结构的仓库：conventions 管强制规范、specs 管设计、
> adr 管决策、AGENTS.md（仓库根）管 AI 进场路由。

## 开发前必读

1. [`conventions/00-项目配置.md`](conventions/00-项目配置.md) — 唯一变量入口（项目名/包名/远端/门禁命令）
2. [`conventions/02-开发红线.md`](conventions/02-开发红线.md) — 八条硬性红线，违反 = review 打回
3. [`STATUS.md`](STATUS.md) — 活页进度卡：当前开发到哪、下一步做什么

## 目录表

| 目录/文件 | 职责 | 内容 |
|---|---|---|
| `conventions/` | 强制开发规范（编号命名） | 00 项目配置（唯一变量入口）/ 01 规范模板 / 02 开发红线 / 03 命名与文案 / 08 提交信息规范 / 规范索引 |
| `specs/architecture/` | 架构与产品规格 | A1-01 产品定位与能力全景 / A1-02 一核多端落地 / A1-03 品牌与业务语言标准（词表单源）/ A1-05 按业务域重写总设计 |
| `specs/domain/` | 领域设计 | A2-01 领域总纲与业务域地图 / A2-11..A2-15 五业务域分册（accounts/execution/usage/health/scheduling）/ A2-02 Connector 规范 |
| `specs/cross-cutting/` | 横切设计 | A4-01 L0 底座设计 |
| `specs/application/` | 应用/前端设计 | A3-01 信息架构与核心页面 |
| `specs/legacy/` | 旧系统知识资产 | A0-01 旧系统知识资产（auto-signin-kit = 协议字典 + 验收基准，**非移植**） |
| `specs/README.md` | specs 入口：层级字母↔子目录映射 + 文档清单 | A 前缀避开能力分层 L0~L7 |
| `adr/` | 架构决策记录（一文件一决策，标题即结论） | ADR-模板 |
| `guides/` | 操作指南 | 01 环境与命令 |
| `plans/` | 交付计划 | M2-用量取证清单（R2 立项取证，待执行）；里程碑总账记于 STATUS.md / A1-01 §6 |
| `scripts/` | 文档配套协作脚本 | — |
| `STATUS.md` | 活页进度卡（多终端同步进度的唯一机制） | 当前现状 / 里程碑 / 下一步 / 已定决策 |
| `design-decisions.md` | 审美决策记录（verify 门禁必产物） | 品牌 / 主题 / IA / 可访问性 / 桌面端 |

## 治理规则

- 单一事实来源；文档描述与实现不一致 → 先改文档再动代码
- 架构裁决 → `adr/ADR-编号-结论式标题.md`；审美裁决 → `design-decisions.md`
- 一份新文档不知道放哪：是"必须遵守的约束" → `conventions/`；是"一次决策及理由" → `adr/`；
  其余按用途：怎么做 → `guides/`；长什么样 → `specs/`；什么时候做 → `plans/`

## 与标准结构的偏差（有意为之）

- `STATUS.md` 代替标准 `TODO.md`：进度卡已承担"要做"清单职能，避免双份事实来源
- `AGENTS.md` 在仓库根（而非 docs/）作为 AI 进场路由，仓库工具按根路径发现它
