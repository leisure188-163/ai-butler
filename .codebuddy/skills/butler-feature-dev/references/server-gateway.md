# server / gateway 端点模式

## 1. server routes（一业务域 = 一模块 = 一文件）

- 路由文件：`apps/server/src/server/routes/{accounts,apps,runs,usage}.py`
- `routes/api.py` 是**纯聚合器**（docstring 明令：新端点先找域，域不存在则新建模块，**禁止回塞 api.py**）；include 顺序 = OpenAPI paths 首现顺序，**插入位置要稳定，防契约指纹漂移**
- 端点 + DTO 同文件：Pydantic `*Out` 模型随域走（先例 `routes/usage.py:16-70`）

端点写法先例（`routes/usage.py:72-91`）：

```python
router = APIRouter(tags=["butler"])

class CollectOutcomeOut(BaseModel):
    account_id: str
    ...

@router.post("/usage/collect", response_model=list[CollectOutcomeOut])
def collect_usage(request: Request) -> list[CollectOutcomeOut]:
    """<一句话语义>。"""
    kit = request.app.state.kit
    outcomes = [kit.collect_usage.execute(...) for account in kit.accounts.list_all()]
    return [CollectOutcomeOut(**fields) for o in outcomes]
```

纪律：
- 路由**不写业务规则**：从 `request.app.state.kit` 取用例执行，core 字面量原样传递（端零映射）
- 分类/谓词只 import core 纯函数（`is_quota_low`、`forecast_exhaustion`），禁止路由里重写判断
- 出参字段与 core 返回逐字段显式映射，不 `**dataclass` 偷懒透传 DO（R7）
- 挂载：`main.py` `include_router(api_router, prefix="/api/v1")`；lifespan 里 `build_engine` + 装配连接器（`BUTLER_SCHEDULE=0` 显式关调度）
- 模块顶部常量放文件头（如 limit 上限），不散落函数内

## 2. 契约流水线（红线 4，改 API 必走）

```
改 routes/*.py → uvicorn 起服务产出 openapi.json → pnpm gen:sdk
→ packages/sdk/src/gen/schema.d.ts + openapi.sha256 指纹更新
→ 门禁第 7 项（契约新鲜度 sha256 比对）PASS
```

忘跑 `pnpm gen:sdk` = 门禁 FAIL。web 侧编译期报错是类型即测试（契约先行）。

## 3. gateway 模块形状

`apps/gateway/src/butler_gateway/`（FastAPI + httpx，与 server 同栈）：

- 数据类 + `from_dict` 逐条校验：`@dataclass(frozen=True)` `RouteRule`/`RouteTable`，非法逐条 `ValueError` 精确中文报错（`routing.py:18-78`）
- 配置三态：**缺失 = 空表合法；非法 = 拒启**；env `BUTLER_*` 覆盖，非法 `raise SystemExit`（`config.py:23-60`）
- 限流器：`AccountLimiter` 用 `@asynccontextmanager async def slot(account_id)` 上下文持槽；每账户 `asyncio.Semaphore` 默认并发 1（保守风控）；不可重入写进契约 docstring；观测面 `in_use` property（`limiter.py:19-64`）
- `/health` 扩节模式：lifespan 装载 state（`app.py:30-42`）→ health dict 加一节（`app.py:48-72`，G3 routes 节先例）
- app 工厂 `create_app()` + 模块级 `app = create_app()`；测试注入点用 `_transport_factory` 这类 kwarg（`app.py:27`）

## 4. server/gateway 测试注入

- server：`TestClient` + env 注入（`BUTLER_DB`/`BUTLER_SCHEDULE=0`）；`FakePort` 接管 `kit` 的用例端口；断言响应值 ∈ core 词表（`apps/server/tests/test_api.py:24-59`）
- gateway：纯函数测试 + `pytest.raises(ValueError, match="中文报错")` 精确匹配（`apps/gateway/tests/test_routing.py:20-101`）
