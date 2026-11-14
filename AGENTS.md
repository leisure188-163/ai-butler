# AGENTS.md · butler Agent 指引

> 给在这个仓库工作的 AI（和人）。本文件只做**路由**，不放规范正文——
> 规则在 `docs/conventions/`，设计在 `docs/specs/`，进度在 `docs/STATUS.md`。

**Butler（AI 智能助手管家）**：本地优先的智能助手管家——统一管理各家 AI 助手的
账户、凭据、权益、用量，并做调度与迁移。架构 = 一核多端 + **按业务域分包**：
`packages/core`（butler_core）唯一业务规则出处，内部按五个业务域 + shared 内核分包
（域图见 A1-05），apps/* 全是薄壳，OpenAPI 契约生成 TS SDK。

写代码或改文档前：

1. **每次会话开始**：读 [docs/STATUS.md](docs/STATUS.md)（活页进度卡：当前在哪、下一步做什么）
2. **查写死值（项目名/包名/远端/命令）**：读 `docs/conventions/00-项目配置.md`（唯一变量入口）
3. **动任何代码前**：读 `docs/specs/architecture/A1-05-按业务域重写总设计.md`
   （域图/包结构/多账号/阶段计划）+ `docs/specs/architecture/A1-02-一核多端落地.md`
4. **写 core / 接入新应用**：读 `docs/specs/domain/A2-01-领域模型与动作模型.md`（总纲）
   + 要写的那个域的分册 `docs/specs/domain/A2-11..A2-15`（accounts/execution/usage/
   health/scheduling）+ `docs/specs/domain/A2-02-Connector-规范.md`
5. **碰凭据/事件/审计**：读 `docs/specs/cross-cutting/A4-01-L0-底座设计.md`
6. **改 UI**：读 `docs/specs/application/A3-01-信息架构与核心页面.md` + `docs/DESIGN-DECISIONS.md`
7. **想参考旧项目 auto-signin-kit**：先读 `docs/specs/legacy/A0-01-旧系统知识资产.md`（**必读**）
8. **任何编码/review 前**：读 `docs/conventions/02-开发红线.md`（八条红线，违反 = 打回；
   含第 8 条「裁决必须回收 spec」）；
   起名/写文案 → `docs/conventions/03-命名与文案规范.md`；
   新增/改路由端点、新建代码文件 → `docs/conventions/04-代码文件组织与长度约束.md`
   （一业务域一模块，600 行硬上限门禁机检）
9. **生成任何 git 提交信息前**：读 `docs/conventions/08-提交信息规范.md`
   （格式 `<type>:[<需求单号>]: <中文主题>`，钩子 `.githooks/commit-msg` 强制校验）
10. **环境与命令**：读 `docs/guides/01-环境与命令.md`
11. **品牌/语言/起名**：读 `docs/specs/architecture/A1-03-品牌与业务语言标准.md`——
    用户可见词以 A1-03 §3 词表 v2 为准（强制规范收编在 conventions/03）
12. 遵守各规范中 ❌ 禁止项；不确定方向时先读对应设计文档，文档没有的 → 提问，别发明

## 会话纪律

- 完成一个里程碑/步骤 → **更新 `docs/STATUS.md`**（这是多终端同步进度的唯一机制）
- 架构裁决 → 追加 `docs/adr/`（`ADR-编号-结论式标题.md`），**同一提交内回收受影响的
  spec**（红线 8）；审美裁决 → `docs/DESIGN-DECISIONS.md`
- 新文档放哪 / 文档体系规则 → `docs/README.md`
