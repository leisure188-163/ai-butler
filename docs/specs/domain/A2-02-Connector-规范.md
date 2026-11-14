# A2-02 · Connector 规范

> 一个 AI 产品 = 一个 Connector 包。本文定义包结构、能力声明、三级扩展、
> 沙箱边界与 PROTOCOL.md 模板。M1 首批四个 Connector 按本文实现。

## 1. 包结构

```
packages/connectors/src/butler_connectors/<id>/
├── manifest.yaml      # 身份 + 能力矩阵声明（唯一入口，注册表据此发现）
├── PROTOCOL.md        # 协议字典（版本化）：端点/加密/幂等/业务码——逆向结论的归宿
├── declarative/       # 三级扩展之一：声明式能力（仅 L1）
│   └── provision.run.yaml
└── adapter.py         # 三级扩展之二：Python 适配器（实现 core 端口）
```

三级扩展之三（独立进程 Adapter）放 `apps/gateway/` 的 provider 插件（R4）。

## 2. manifest.yaml

```yaml
id: trae_cn
display: Trae CN
capabilities:
  provision.run:                  # 能力 id：动词.名词（provision/usage/session/health）
    kind: declarative             # declarative | adapter | gateway
    entry: declarative/provision.run.yaml
  usage.read:
    kind: adapter                 # 复杂能力用代码
credential:
  kinds: [ss_aes]                 # 支持的凭据类型
  unlock: local-client            # 解锁方式: local-client | vault | manual
schedule:                         # 调度声明（cron 缺省值，用户可在 UI 改）
  provision.run: ["09:05", "13:05", "19:05", "23:05"]
```

规则：
- 注册表只读 manifest，不 import 业务代码；能力未声明 = UI 不渲染该能力的入口
- `display` 用产品名（用户语言），`id` 是稳定技术标识

## 3. 三级扩展与适用边界

| 级别 | 适用 | 谁写 | 约束 |
|---|---|---|---|
| 声明式 YAML | 纯 HTTP：登录态文件直读 + 接口签到（trae） | 用户/社区 | **仅限 L1**；五段式：auth / status / claim / business_codes / schedule |
| Python 适配器 | 需解密/客户端交互/CDP（qoder、doubao、workbuddy） | 官方 | 实现 core 端口；按 PROTOCOL.md 重写，不抄旧代码 |
| 独立进程 Adapter | 高并发反代 provider（R4） | 官方 | 禁止声明式；只做转发与计量 |

**kind 收敛原则（扩展判据，2026-11-11 裁决）**：应用接入面 = **声明 + 可枚举
kind 的组合**，一套运行时 + N 份数据——绝不 per-app 平行代码（历史项目教训：
domains/trae 与 domains/qoder 各写一份 service/api/auth，同一签到逻辑 N 遍）。
- 协议特殊性（凭据解锁/动态请求头/签名算法）只允许以 **kind** 形态扩展：
  新 kind = 引擎加一个处理器，所有同 kind 应用共享；出现在"这个应用专用"的
  位置 = 违规
- per-app 代码仅剩一种合法形态：**core 端口实现**（协议复杂到声明表达不了时，
  如 CDP 编排），且只准实现 `capabilities()` + `run()`——dock/vault/幂等/
  调度/审计仍是底座的，不许自带平行件
- 判据口诀：这段逻辑换成另一个应用还能用吗？能 → 做 kind；不能且只有这一个
  应用要 → 先问是不是协议没取证全，取全了还特殊 → 端口实现

## 4. 声明式 schema（升级自旧 STD-07：从"只能声明签到"到能力矩阵）

```yaml
# declarative/provision.run.yaml
auth:
  kind: session-file              # 凭据来源（vault 负责解锁）
  paths: ["%APPDATA%/Trae CN/User/globalStorage/storage.json"]
status:                           # 查询接口：判断"今天领了吗"
  request: { method: GET, url: "https://…/api/xxx", headers: {…} }
  expect: { field: "data.today", equals: true }
claim:                            # 领取接口
  request: { method: POST, url: "https://…/api/claim" }
business_codes:                   # 业务码 → core 结果词汇（唯一翻译点）
  "2000": CLAIMED
  "2001": ALREADY
  "401":  NO_AUTH
window: { refresh_at: "00:00" }   # 签到窗口（签到日 ≠ 自然日）
```

规则：business_codes 是声明式与 core 的**唯一翻译边界**；声明里出现
schema 外字段直接报错（`extra=forbid`，继承旧仓库"显式报错不静默兜底"的教训）。

## 5. 沙箱边界（L7 市场的前置条件，M1 起就执行）

- 声明式 Connector 只能访问 manifest 内声明的域名（URL 白名单，加载期校验）
- Python Connector 进程内运行但凭据经 vault 注入（拿不到别的账号的凭据）
- 凭据最小授权：Connector 申报用哪几种凭据，vault 只解密注入那几种
- 第三方 Connector（非官方目录）默认降级运行：无 shell/无任意路径读，违规即卸载

## 6. PROTOCOL.md 模板

```markdown
# <id> 协议字典 v<semver>
> 来源：逆向结论 / 官方文档。每条结论附验证日期与环境。
## 1. 端点清单        method / path / 认证方式 / 已知变更历史
## 2. 认证与凭据      凭据类型 / 解锁协议 / 有效期与刷新
## 3. 关键请求形状    必需头（如设备风控头）/ 签名算法 / 请求体
## 4. 业务码字典      码 → 语义 → core 结果词汇映射
## 5. 幂等与重试      哪些操作重试安全 / 领取是否幂等 / 窗口语义
## 6. 已知风险        触发风控的条件 / ToS 边界
```

规则：PROTOCOL.md 是 Connector 的**唯一事实来源**——适配器代码里不允许出现
文档没有的端点/魔法值；发现新协议先改文档再改代码。

## 7. 实现顺序（M1，由简到繁验证底座）

1. trae_cn（纯声明式）→ 2. qoder_cn（声明式 + 设备风控头）→
3. doubao_cn（CDP 编排）→ 4. workbuddy_cn（签到最小集，ADR-006 收敛）

**硬标准**：每个 Connector 不加特殊分支接入新模型；某个必须写例外 →
停下来改模型。每个完成后跑行为一致性对照（见 `../legacy/A0-01-旧系统知识资产.md` §4）。

## 8. 测试与 CI 边界（M1 起执行）

CI 只在 ubuntu 跑——平台特有调用（Windows DPAPI / macOS Keychain）与真浏览器
（CDP）在 CI 里**测不了**，测试体系按可注入性设计，规则四条：

1. **连接器测试必须离线**：HTTP 一律经 Transport 端口注入剧本化 FakeTransport
   （逐次响应清单，零真网 IO）；凭据经 FakeVault 注入桩值。测试里出现真域名
   请求 = 打回。
2. **平台 API 走工厂注入**：DPAPI/Keychain 等系统调用收敛在 adapter 模块，经
   工厂/runner 注入；非 Windows/非 macOS 环境用假 api 单测（CI 照跑，本仓
   `credman_windows` / `keychain_macos` 即此模式）。
3. **CDP 测试不起浏览器**：探测逻辑与浏览器操作分离；浏览器交互层用假 page
   对象测（M1 doubao_cn 落地时照此拆分）。
4. **真上游验证 = 行为对照验收，手动真机跑**：PROTOCOL.md 附脱敏响应样本；
   样本含真实 token/uid 不得入库——先脱敏再提交。


## 9. 多账号 dock/import 取证结论（ADR-008 §3，2026-11-14 重写 P5）

core/engine/server 已按 ADR-008 支持"一应用 N 账户"（`account_key`、
`AppOut.account_ids`、一键领取逐账户发起）。连接器侧取证结论如实登记如下，
**不虚报未验证能力**（红线 5）：

| 连接器 | dock 现状 | 多 profile 取证 |
|---|---|---|
| trae_cn / qoder_cn / doubao_cn / workbuddy_cn | 单账号（首账号 `main`） | 待真机验证多开/多 profile 的凭据目录布局，未取证不推断 |
| chatgpt_web / claude_web | 单账号网页会话通道 | 多浏览器 profile 的 CDP 端口发现待真机验证 |

**扩展点已预留**：`butler_core.accounts.ports.SessionSourcePort.enumerate_accounts()`
产出 `(account_key, display_name)`，`RegisterAccount.import_from_source()` 逐账号
入库；某连接器完成真机取证后，按其 PROTOCOL.md 新增"多 profile 目录形状"小节，
再在 dock 流程接入，无需改 core/server 契约。
