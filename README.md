# Kabao · 卡包

**One wallet for all your AI accounts.** 你的所有 AI 账号权益，都收在这一个卡包里——领取、计量、调度，一包管尽。

本地优先的 AI 账号管家：统一管理各家 AI 编程助手的**账号、凭据、权益、用量**，并在它们之间做**调度与迁移**。

```
┌ L1 权益   签到/积分/任务（活动时间表）              ← 继承 auto-signin-kit
├ L2 用量   token 采集 · 额度雷达 · 成本顾问
├ L3 网关   账号池 · 个人反代 · 规则引擎（独立进程）
├ L4 会话   账号切换携带上下文（local/inject/server 三级）
└ L0 底座   凭据保险库 · 账号健康 · 事件通知 · 审计
```

## 文档导航

| 文档 | 内容 |
|---|---|
| [A1-01 产品定位与能力全景](docs/specs/architecture/A1-01-产品定位与能力全景.md) | 定位 / 品牌与词表 / L0~L7 能力 / 活动时间表 / 里程碑 / 合规边界 |
| [A1-02 一核多端落地](docs/specs/architecture/A1-02-一核多端落地.md) | 分层与依赖方向 / 领域模型概览 / Connector 机制 / 门禁 |
| [A2-01 领域模型与动作模型](docs/specs/domain/A2-01-领域模型与动作模型.md) | 聚合根 / 结果词汇单源 / Action-Run / Trigger / Event / 端口 |
| [A2-02 Connector 规范](docs/specs/domain/A2-02-Connector-规范.md) | manifest / 三级扩展 / 声明式 schema / 沙箱 / PROTOCOL.md 模板 |
| [A3-01 信息架构与核心页面](docs/specs/application/A3-01-信息架构与核心页面.md) | 五导航 / 页面规格 / 旅程锚点 / 渲染纪律 |
| [A4-01 L0 底座设计](docs/specs/cross-cutting/A4-01-L0-底座设计.md) | 凭据保险库 / 健康中心 / 事件总线与通知 / 审计 |
| [A0-01 旧系统知识资产](docs/specs/legacy/A0-01-旧系统知识资产.md) | auto-signin-kit = 协议字典 + 验收基准（**非移植**）；带/不带清单 |
| [design-decisions 设计决策](docs/design-decisions.md) | 品牌 / 主题 / IA / 可访问性 / 桌面端 |
| [conventions 开发规范](docs/conventions/规范索引.md) | 00 项目配置（变量唯一入口）/ 02 开发红线 / 03 命名与文案 |
| [STATUS 进度卡](docs/STATUS.md) | 当前现状 / 里程碑 / 下一步 / 已定决策（每次会话开始先读） |

## 架构（一核多端）

```
apps/cli | apps/web | apps/desktop | apps/uniapp     ← 壳（薄，零业务规则）
                ↓ OpenAPI 契约（packages/sdk 自动生成 TS）
apps/server（主控）→ packages/core（唯一业务规则出处）→ packages/engine（出站适配器）
apps/gateway（反代独立进程，R4）
packages/connectors/（三级扩展：声明式 YAML / Python / 独立进程）
```

业务逻辑只写一份；契约先行（后端改字段，前端编译期报错）；依赖方向恒向内。

## 开发

```bash
cp .env.example .env
uv sync && pnpm install
uv run uvicorn server.main:app --reload     # server
uv run kabao cards list                     # CLI
pnpm dev:web                                # Web
cd apps/desktop && npm i && WEB_URL=http://localhost:5173 npm start   # Electron 壳
```

架构自检（八项门禁，必须全绿）：

```bash
python scripts/verify_project.py --project . --test
```

## 免责声明

L1/L2 仅操作用户本人账号；L3 反代定位「个人多账号聚合（仅本机）」，使用须遵守
目标平台服务条款，风险自负。完整声明见 specs [A1-01](docs/specs/architecture/A1-01-产品定位与能力全景.md) §7。

## License

MIT
