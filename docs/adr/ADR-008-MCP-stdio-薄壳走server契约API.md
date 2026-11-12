---
name: kabao-adr-008
description: MCP stdio 薄壳宿主形态——零 core/engine import，纯 HTTP 走 server 契约 API；工具集三件不扩。TRIGGER when 讨论 MCP 工具、LLM 客户端接入、apps/mcp 时
version: "0.1.0"
level: must
---

# ADR-008 · MCP stdio 薄壳走 server 契约 API

- **状态**：Accepted
- **日期**：2026-11-12
- **决策者**：用户（已裁②③④）+ Agent 落地
- **关联**：A1-02（一核多端）、ADR-003（target 级端口路由）、红线 2/4/5

## 背景

R2 收尾需要把卡包能力暴露给 LLM 客户端（Claude Desktop / Cline 等）。候选：

1. **stdio 宿主直调 core/engine**（CLI 同款进程内装配）；
2. **stdio 宿主走 server 契约 API**（HTTP 客户端，server 常驻前提）；
3. stdio 宿主内嵌 uvicorn（desktop 离线模式同款）。

约束：薄壳不应持有业务装配面；MCP 宿主随 LLM 客户端启停（短生命周期），
而卡包的调度/采集是常驻 server 的职责；工具语义字面量必须 core 单源。

## 决策

**方案 2：stdio 宿主 = 纯 HTTP 投影端，零 core/engine import**。流程要点：

1. 落点 `apps/mcp`（包名 `kabao-mcp`，src 包 `kabao_mcp`——**不得叫 `mcp`**，
   与官方 SDK `import mcp` 冲突）；SDK 用官方 `mcp` 2.x（`MCPServer`，
   stdio transport；v1 的 FastMCP 已更名）。
2. base URL 取 `KABAO_SERVER_URL`（默认 `http://127.0.0.1:8000`）；
   server 不可达 → 显式报错并附启动命令，绝不内嵌拉起/静默兜底（红线 5）。
3. 工具集三件（**不含领取扩展、不含用量采集触发**——采集归 server 调度与 web）：
   - `query_quota` 查额度 = GET /usage/radar 的 packages + forecasts + quota_low 投影；
   - `query_usage` 查用量 = 同一雷达响应的 aggregate_summary + recent_ledger 投影；
   - `claim_now` 触发领取 = POST /runs（target 必填，结果字段直传）。
   两查询工具可选 `provider` 过滤（选取不是映射）；status/signal/字面量
   core 出产直传，端零映射（红线 2）。
4. server 端**零改动**（现有端点已够用）→ 无契约再生成。

明确排除项：MCP 工具不做批量/编排动作（一次一 call）；网关/反代语义（R4）
与本薄壳无关；web 端功能一律不复制进工具面。

## 后果

**正面**：

- 薄壳零业务装配面：连接器端口、调度、DB 全留 server——LLM 客户端频繁启停
  不产生装配开销，也不与常驻调度抢 SQLite。
- server 是唯一契约出处，MCP 面随契约自然演进；测试只需 MockTransport 假 server。

**负面/约束**：

- 依赖 server 常驻：未启动时工具只能显式报错引导（这是特性不是缺陷）。
- 多一层 HTTP 往返（本地 127.0.0.1，可忽略）。
- `mcp` SDK 拉入 anyio/starlette/uvicorn 等传递依赖——只进 apps/mcp 与
  uv.lock，不进 core。
