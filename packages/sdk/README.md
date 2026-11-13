# @kabao/sdk

Kabao（卡包）server 的 OpenAPI 契约类型包——由 `apps/server` 的 FastAPI app 经
[openapi-typescript](https://github.com/openapi-ts/openapi-typescript) 生成，
是 web 端 DTO 的**单一类型事实源**：`import type { components } from "@kabao/sdk"`，
零手写字段清单——server 改字段，再生成本包即同步。

## 再生成

server 路由改动后，在仓库根执行：

```sh
pnpm -C <repo根> --filter @kabao/sdk generate
```

产物为 `src/gen/schema.d.ts`；同目录 `openapi.sha256` 是契约指纹
（`sha256(json.dumps(app.openapi()) + "\n")`），与仓库 verify 门禁同口径，
指纹漂移即契约变更。

## 版本口径

包版本随 server 契约形状演进（破坏性形状变更升 major）。当前对应关系见仓库
`docs/STATUS.md`；本包只含类型（`.d.ts`），零运行时依赖。
