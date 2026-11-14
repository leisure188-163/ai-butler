---
name: kabao-adr-001
description: 出站适配器（Vault/SQLite/HTTP/调度器）独立成 packages/engine 包，bridge.py 唯一出桥，对齐 COLA infrastructure 层。TRIGGER when 写适配器/装配依赖/讨论 core 依赖时
version: "1.0.0"
level: must
---

# ADR-001 · 出站适配器独立成包 packages/engine（COLA infrastructure 正形）

- **状态**：Accepted
- **日期**：2026-11-10
- **决策者**：hiclaw520 + AI（经业界标准查证后裁决）
- **关联**：A1-02 §2/§5、A4-01 §5、02-开发红线 §1.3（core 纯净）、cross-platform-arch hexagonal-arch.md R1-R9

## 背景

A1-02 §2 分层图画了 `engines/`（出站适配器：HTTP / 凭据解锁 / CDP / SQLite / 调度器），
但 §5 目录规划和脚手架都没有给这个层落点——M0 编码第一步就会撞上：Keychain(Vault)、
SQLite 仓储、事件总线落地、调度器这些适配器**需要被 server 与 CLI 共享**（两端都直调 core）。

候选方案：

| 方案 | 内容 | 问题 |
|---|---|---|
| A | 独立包 `packages/engine` + bridge.py（skill 规约正形） | 模板里没有，需新建 |
| B | 独立包但无 bridge，端直接 import 适配器 | verify 六边形门禁继续失效 |
| C | 端内适配器（skill 设计备忘 2026-11-10 的 scaffold 变体） | Keychain 等要在两端复制；该备忘明确只针对小 demo |

约束与依据：

1. **业界标准（COLA 4.0，阿里）**：四层 = 适配器层 / 应用层 / 领域层 /
   **基础设施层（infrastructure）**。基础设施层承载持久化、外部服务、RPC 等技术细节，
   通过**依赖倒置**实现领域层定义的端口；start 层（组合根）负责装配。
   本项目 skill 的 hexagonal-arch.md §1 已给出同构对照：
   `infrastructure → packages/engine`、`start → apps/server 组合根 / bridge 工厂`。
2. **仲裁约定**：STATUS.md 环境备忘"遇争议以 cross-platform-arch skill 为准"；
   skill 正形即方案 A（R1 纯净 / R2 方向 / R4 唯一出桥 / R6 用例层编排唯一入口）。
3. **门禁现状**：`verify_project.py.check_hexagonal` 写死 `packages/engine/src`，
   不建该包则"六边形桥闭合"检查静默跳过，七项门禁退化成六项有效
   （与 skill 设计备忘 hexagonal-gate-alignment 的审计发现互证）。
4. **红线 3**：core 零框架依赖 → keyring 等第三方库进不了 core，适配器必须在外层。

## 决策

**方案 A：出站适配器独立成 `packages/engine`（包名 `kabao_engine`）**，流程要点：

1. 依赖方向恒定：`端 → core`、`engine → core`；engine 不依赖任何端。
2. `kabao_engine/bridge.py` 是端触达引擎的**唯一出桥**（R4）：装配适配器 →
   构造用例 → 把引擎原始输出经 core 领域词汇归一后返回。
3. 适配器按**能力**分子包（`vault/` `ledger/` `scheduling/` `http/`…），
   禁止用旧业务目录名（R3）。
4. `core/bootstrap.py` 保留为纯装配根（只认端口协议）；bridge 调它并传具体适配器。
5. server / CLI 统一 `from kabao_engine.bridge import ...`；
   脚手架残留的 `apps/server/adapters/`、`apps/cli/repo.py` 在 M0 重构时迁入 engine 后删除。

明确排除项：

- `packages/connectors/`（M1 的 Connector 包）**不属于** engine——Connector 是被
  core 端口调度的领域扩展，不是基础设施适配器，见 A2-02 §1。
- M3 的网关独立进程（`apps/gateway`）不是 engine 的一部分，仅通过 IPC/HTTP 与主控通信。

## 后果

**正面**：

- 与 COLA/skill 标准完全同构，新人按业界心智模型即可读懂
- server / CLI / 桌面 sidecar 共享同一批适配器，无端间复制
- verify 六边形门禁原样生效（无需改门禁代码），七项门禁重新齐整
- 换实现（Keychain→其他）只动 engine，core 与端零改动

**负面/约束**：

- 多一个包与 bridge 装配纪律；端绕过 bridge 直 import 会被 verify 拦截，属预期
- bridge 装配发生在 engine → engine 依赖 core，注意不要反向（check_dep_direction 兜底）
- 本决策豁免流程走 R9：后续任何"端直连适配器"的需求须先记 DESIGN-DECISIONS 再实施
