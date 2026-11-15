---
name: butler-feature-dev
description: ai-butler（butler）新增业务功能的标准编码流程与分层代码格式。TRIGGER when 在本仓库新增/修改业务逻辑、加 core 端口或用例、加表或字段、加 server/gateway 端点、加 web 页面、实现新连接器、为某功能补齐多层实现、跑门禁验收或按规范补测试；DO NOT TRIGGER when 纯文档/文案修改、只调样式 token、升级依赖版本、研究旧系统 auto-signin-kit（先读 docs/specs/legacy/A0-01）。
license: MIT
metadata:
  version: "1.0.0"
---

# butler 新增业务功能标准动线

一句话：**一个功能 = 一条穿层动线**——core 定规则（domain/ports/usecase）→ engine 落适配器 → bridge 装配 → server/gateway 出契约 → web 消费 → 四层测试 → 门禁九项 → 文档同提交收编。每层形状固定，照 `assets/` 模板起手。

## 开始前必读（本仓库已有路由文档，本 skill 不重复其正文）

1. `docs/STATUS.md` 进度卡（当前在哪、下一步）
2. `docs/conventions/01-开发红线.md` 八条红线（本 skill §硬规则速查只是摘要）
3. 写对应域的代码 → `docs/specs/domain/A2-01` 总纲 + 该域分册 A2-04..A2-08

## 标准动线（层序，逐层照模板）

1. **domain**（`packages/core/src/butler_core/<域>/domain.py`）：frozen dataclass + `__post_init__` 校验抛 `XxxInvalid(DomainError)`；谓词纯函数单源。→ 模板 `assets/domain.py.tmpl`
2. **ports**（同域 `ports.py`）：ABC 或 Protocol，契约写 docstring 引 spec 编号；端口语义错误也定义在此。
3. **usecase**（`<域>/usecases/<动词>.py`，一用例一文件）：`@dataclass` 类 + 端口字段注入 + 时钟可注入；docstring 写「干净路径 / 非法输入显式抛 / 侧效应失败留痕不打断主流程」三段语义。→ 模板 `assets/usecase.py.tmpl`
4. **engine 适配器**（`packages/engine/src/butler_engine/<域>/sqlite.py`）：实现端口；`_SCHEMA` DDL 常量 + 每操作一连接；改表后跑 `scripts/dump_db_schema.py` 同步 `db/schema.sql`。→ 模板 `assets/sqlite_store.py.tmpl`
5. **bridge 装配**（`packages/engine/src/butler_engine/bridge.py`）：`build_engine()` 构造并塞进 `EngineKit`；要配置就加 kwarg；注册类端口加 `register_*_ports()` 防撞车方法。
6. **server / gateway**：端点归入或新建 `apps/server/src/server/routes/<域>.py`（Pydantic `*Out` 随域走），按序 include 进 `api.py`，**立刻跑 `pnpm gen:sdk` 刷契约**。→ 模板 `assets/server_route.py.tmpl`
7. **web**：`types.ts` 从 `@butler/sdk` 派生（禁手写字段形状）→ `api.ts` 加域分节端点函数 → composable 动作 → page/组件（props/emit 类型化，BEM 类 + tokens.css 变量）。
8. **测试**：core 用例测试 + engine 分册测试（真 SQLite tmp_path + Fake 端口）+ server TestClient 冒烟。→ 模板 `assets/test_usecase.py.tmpl`
9. **文档收编**（红线 8，同一提交）：更新对应 A2-xx 分册节 + `docs/STATUS.md` 进度卡。
10. **门禁**：`python scripts/verify_project.py --project . --test` 九项全绿 → 提交信息 `<type>:[<单号>]: <中文主题>`（钩子强制校验，无单号用 `[0]`）。

任何一步 FAIL：先修复再走下一步；SKIP 不算通过（测试没跑 ≠ 测试通过）。

## 硬规则速查（详情见 references/，违反 = 门禁 FAIL 或打回）

- 端零映射：业务规则只落 core；端只消费 core 出产谓词（signal 五分类/quota_low），禁 `if status in [...]`
- core 零框架依赖（禁 fastapi/pydantic/typer…，机检）；域间互不 import（domain.py 只准 import `butler_core.shared`）
- 契约先行：改 API 必跑 `pnpm gen:sdk`；web DTO 派生自 `@butler/sdk`
- 显式报错不静默兜底；禁 try/except 吞错降级（意外异常 = 落账后 re-raise）
- 设计 token 只用 `apps/web/src/styles/tokens.css`
- 一业务域 = 一模块 = 一文件；新端点禁进聚合器 `api.py`；单文件 400 行软警戒 / 600 行硬上限（机检）
- 文案 ∈ 词表 v2；禁用退役词（卡包/泊位/账号/首页…）
- 旧仓库 auto-signin-kit 是协议字典 + 验收 oracle，不是代码来源（红线 1；详见 `docs/specs/legacy/A0-01`）

## 参考文件（按需加载，勿一次全读）

- `references/core-patterns.md` — domain/ports/usecase 骨架 + 错误处理三段语义 + 模型分层规约。写 core 前读。
- `references/engine-bridge.md` — Sqlite*Store 模式、表设计纪律、build_engine 装配。写 engine 前读。
- `references/server-gateway.md` — routes 域模块、契约流水线、gateway 配置拒启模式。写端点前读。
- `references/web-patterns.md` — types/api/composable/页面/BEM/token。写 web 前读。
- `references/tests-and-gates.md` — 四层测试写法、门禁九项、验收纪律、提交与文档收编。提交前读。

## assets 模板使用

模板是**起手脚本**：复制到目标路径后，把 `<占位符>` 换成真实命名，删除与本功能无关的注释行；docstring 里的 spec 引用必须换成当前真实编号（编造引用 = 违反红线 8）。

## 配套（通用版）

本 skill 的去项目化通用版 = cross-platform-arch 集合的 `feature-dev-flow`
（带项目特性参数表，占位符实例化后即可用于任何一核多端项目）。其他项目用
通用版；本项目用本 skill（参数已填好）。
