# 测试、门禁、提交与文档收编

## 1. 测试分层模式

位置 `<pkg>/tests/test_<主题>.py`；core 另有分册 `tests/butler_core/test_butler_*.py`。全部裸 `assert`，无 unittest 类风格。

- **core 用例测试**（`packages/core/tests/test_usage.py:22-64`）：
  - `_pkg(**over)` 工厂函数造默认实例 + 逐参覆写
  - 非法输入 `pytest.raises(XxxInvalid)`（精确异常类型，别 `Exception`）
  - 谓词边界表驱动断言；回归注释写日期 + 动机
  - 零 mock IO：Fake 端口即可，毫秒级
- **engine 分册测试**：
  - store：`@pytest.fixture` 真 SQLite（`tmp_path`）+ 往返保真（frozen dataclass 全字段 `assert row == s`）+ 排序契约 + 重开读回
  - bridge：`build_engine(tmp_path / "butler.db")` → `kit.register_*_ports(targets={...: FakePort(...)})` → 执行 → `kit.bus.drain()` 断事件 → 关 kit 重开第二个 kit 验持久化（`test_bridge_usage.py:39-70`）
- **server**：`TestClient` + env 注入（`BUTLER_DB`/`BUTLER_SCHEDULE=0`）+ `FakePort` 接管 kit；断言响应 ∈ core 词表（`test_api.py:24-59`）
- **gateway**：纯函数 + `pytest.raises(ValueError, match="中文报错")`
- 注入原则：真 vault（memory backend）/真引擎 + `tmp_path` 假库 + 假端口 + 可注入时钟——**不 mock 被测对象本身**

## 2. 门禁九项与验收纪律

唯一命令：

```bash
python scripts/verify_project.py --project . --test
```

九项（`verify_project.py:7-24`）：结构完整 / core 纯净 / 依赖方向 / 域隔离 / 六边形桥闭合 / Token 闭合 / 契约新鲜（openapi sha256）/ 无空包 / 600 行硬上限 + 测试（`uv run pytest -q` + `vue-tsc --noEmit`）。

验收纪律（提炼自 arch-verify skill，红线 7）：
- 任何一项 **FAIL 必须先修复**再走后续流程
- **SKIP ≠ PASS**：因缺 uv 等原因没跑的检查保持 SKIP，不得当成功汇报
- **测试没跑 ≠ 测试通过**：`--test` 无法执行时判 FAIL
- 汇报时贴真实门禁输出（PASS 行只列真正执行过的检查）
- `--project .`（用 apps/web 会误报缺 core 文件）
- 门禁自身改动 = 架构裁决，走 ADR + 同提交回收 spec（红线 8）

## 3. 提交信息（钩子强制）

```
<type>:[<需求单号>]: <中文主题>
```

- type ∈ feat/fix/refactor/docs/chore/build/test；无关联单号用 `[0]`
- 单行、动词开头、≤100 字、不加句号；一次提交一个意图
- `.githooks/commit-msg` 强制校验（postinstall 自动装）；merge/revert 放行

## 4. 文档收编（红线 8：同一提交）

功能落地提交必须包含：
- 对应 A2-xx 域分册受影响小节同步更新（编号引用要真实）
- `docs/STATUS.md` 进度卡加一段（格式仿 R4-Gx 先例：「core 端口/用例 → engine 实现 → bridge 装配 kwarg → 测试数 → 门禁绿 → 分册已收编」）
- 架构裁决 → 追加 `docs/adr/ADR-编号-结论式标题.md`；审美裁决 → `docs/DESIGN-DECISIONS.md`
- 编造 spec 引用 / 静默让 spec 过期 = 违反红线 8，打回

## 5. 常用命令速查

```bash
python scripts/verify_project.py --project . --test   # 门禁九项
uv run pytest -q                                      # 全量测试
pnpm gen:sdk                                          # 刷契约
pnpm dev:web                                          # web dev server
uv run uvicorn server.main:app --reload               # server
uv run python -m butler_gateway                       # gateway
pnpm --dir apps/web exec vue-tsc --noEmit             # web 类型检查
python scripts/dump_db_schema.py                      # 改表后同步 db/schema.sql
uv run butler <命令>                                  # CLI
```
