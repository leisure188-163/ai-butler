# STATUS · 进度卡（每次会话开始先读我）

> 更新纪律：完成一步就改这张卡。格式固定，方便任何终端的 AI 秒懂现状。
> 最后更新：2026-11-16

## 一句话现状

**豆包双账户纳管落地（2026-11-16）**：多账户底座本已就绪（调度 per-account
checkin.py L62 / 用量 bridge 遍历 / A2-04 account_key），缺口只在豆包切号。
CDP 真机取证（PROTOCOL §9）：客户端菜单无一键切换列表、「添加账号」直通登录页
（手机号/扫码需人工参与）→ **切号不自动化**（ADR-007 决策 7），按用户裁决降级
「只监控不切号」：身份判定（identity.py：`sec_user_id` localStorage + chip 昵称）
→ run/dock/usage 三处身份守卫——**绝不签错账户**；第二账户
`doubao_cn:u66b1e22d`（Leisure520）已登记，活跃 main（逍遥酒鬼）签到照常
ALREADY ✓，B 在 main 会话在场时保守 PENDING（双会话并存语义待下轮取证）。
**环境根治**：本机文件虚拟化层拦截一切 sqlite 伴生文件（-wal/-shm/-journal，
四次 disk I/O error 实证）→ engine 五处 `journal_mode=OFF`（无伴生文件，崩溃
丢最后一条写可接受）+ `BUTLER_DB` 补实现（docstring 承诺未实现的老账）+
**数据根迁至项目内 `data\database\butler.db`**（用户裁决：项目根下建 `data\`，
database/ 放运行库 gitignore、sql/ 放 schema 导出入库版本化，项目数据闭环；
home 目录全被锁 D 盘可写；历史台账已迁移；启动脚本 `scripts\start-server.ps1`
固化 BUTLER_DB；00-项目配置 `{data-root}` 收录）
+ gateway 测试隔离修复（BUTLER_DB→tmp_path）。全量 640 passed。

**豆包签到误判根因修复 + 页内 fetch 取证（2026-11-16）**：用户反馈豆包每次
签到弹窗且常判失败需人工补签 → CDP Network spike 取证两项定案：①当日两次
FAILED 实为**点击已生效、状态翻转有延迟**（复查 3s 即查过快；spike 首次点击
实际签上，`continuous_days=10`）→ 点击后复查改**退避 3 次**（3s/5s/8s，
`_RECHECK_DELAYS`）再判 FAILED，`cdp.py evaluate` 补 `awaitPromise` 形参；
②页面 fetch 拦截器**自动签名**实证（`byted_acrawler` 自动补 msToken/a_bogus）
→ ADR-007 预留「页面内 evaluate fetch」升级路径可行性坐实，写接口形状待
下一未签班次取证（裸 HTTP 写禁令不变）。收编 PROTOCOL §1.2/§3/§5/§6⑤ +
ADR-007 决策 6 + **A2-02 §6 新增「写动作判定红线」三条**（用户裁决：送达+成功
信封≠业务成功 / 复查必退避 / 判失败必留证，全连接器永久继承），豆包分册 3 新测试。**弹窗问题定位**：活动页 tab 已有复用
（attach existing），弹窗仅发生于 tab 不在/客户端未运行（dock 重启）——
fetch 化可进一步后台化，待写接口取证后一并裁。

**暖纸绿纸感 + 仪表盘 v6.3/v7 改版落地（2026-11-16）**：参考用户提供的
清新工作台风截图实施——① tokens.css warm 块重定调「清新绿纸」（浅绿纸底
#EAF2E6 + 白卡 + 墨绿 #1D3326 + 叶绿 #2F7D4E，阴影绿调；主题名不动）；
② D2「无彩色装饰」放宽一档 = KPI 彩色功能图标片（色表功能分类不表状态，
signal 染色纪律不变）+ 健康/动作 36px 占比环（只画真实比值）；
③ 仪表盘双栏重排（左待办 TodoRail / 右新组件 QuickPanel = 快捷入口四片
纯导航 + 班次时刻卡）+ 签到条带通栏收尾，≤900px 转单列。
裁决收编 DESIGN-DECISIONS D2 v7 / D3 v6.3 + A3-01 §2 仪表盘段同批改写。
vue-tsc/build 绿；浏览器走查三项 PASS（暖纸绿纸感生效、新布局齐全、
切回纸墨无错乱 console 零 error）。**Windows 机环境坑沉淀**：PATH 首位
hermes uv 损坏须用 `~/.local/bin` uv；uv trampoline 缺陷 → `uv run pytest`/
`uvicorn` 一律走 `python -m`；pnpm 装依赖须 `--config.node-linker=hoisted`
（默认 junction 会被文件虚拟化层指到沙箱缓存成死链，@butler/sdk 死链已用
真实目录拷贝修复）；server 后台直启会撞 SQLite「unable to open database
file」，前台起超时转后台即可。门禁 pytest 632 passed 全绿（含上午三处
Windows 断言修复 cdef375）。

**qoder 领取链复现升级（2026-11-15）**：用户重登（auth.v1.dat 20:57 重写）
→ 重扫入库 → 解锁链全绿（dt- token + refreshToken）→ 直连仍
`401 TOKEN_EXPIRE`——「重启客户端重扫」旧处置口径**失效**，新 token 即被
服务端判 not active = 行为变化（疑似接口收紧会话校验）。**挂账转 Windows
oracle 对照**：Windows 也 401 → 链路转观察项不硬绕；Windows 正常 → 对照
mac 头组差异。PROTOCOL qoder §1 已收编。

**R5-S1 会话扫描入库落地（2026-11-15）**：Session 实体补 `kind`
（SessionKind: workspace|conversation）+ `SessionLevel` 枚举化；端口增
`scan_sessions`（SessionSighting：location/kind/level/device_ref=供应商侧
账户标识，绑定不可得如实 None）；core 用例 `scan_sessions`（vault device
凭据匹配绑定 → (location,kind,level) 去重幂等入库 → repo 回写；绑定不可得
如实 unbound 分列不入库）；trae 扫描器实装（registry 显式工厂契约
`build_session_source()`；只读 `mode=ro` 查 key 名不取值；坏库/锁死如实跳
过）；bridge `register_session_source`（防撞车）+ server
`POST /accounts/{id}/sessions/scan`（未装配如实 503）+ 名册投影带 sessions
+ web 账户详情「会话」节 + 「扫会话」按钮（四层 emit 链）。accounts 表增
sessions JSON 列（ALTER 自迁移）+ schema.sql 同步。**取证发现（S1.5 挂账）**：
trae `device_dn`=设备号 ≠ state.vscdb 前缀=账户 id（本机两账户 135…/236…）
——绑定数据面待 dock 增捕 `aha_account_id`（storage.json `icube_gtm`/
`checkin1024.*` 键名明文可取）；真机 38 观测全 unbound = 台账语义如实呈现
非缺陷。新测试 18 项，门禁九项绿，A2-04 §3/§4.1 已收编。

**R5-S0 收口（2026-11-15）**：ADR-013 六项裁决落档（A3 分 kind 首批
workspace / trae 先行 / 模板注入 / 官方能力边界 / accounts 域编排 /
session-snapshots 两代 + CLI restore）；trae_cn 只读取证 spike 回收
PROTOCOL §10——**workspace kind 本地可迁**（workspaceStorage 目录级 +
globalStorage/settings/snippets，**多账户 = key 前缀隔离**不能整库拷）、
**conversation 本地不可迁**（ChatSessionStore.index 仅 26 字节指向云端，
正文在服务端 → server 级），裁决 A3 被取证验证。下一步 S1：
Session 实体补 kind + SessionSourcePort 实装（trae）。

**R5 立项：会话迁移设计前置清单出炉（2026-11-15）**：`docs/plans/03-R5-会话
迁移设计前置清单.md`——汇编既有锚点（Session 实体/SessionSourcePort 已留
零装配、网页两家排除首批、无 legacy oracle），列 6 个概念裁决点（**裁决 A
「会话」定义** = 对话历史 vs 工作区上下文 vs 分 kind、首批家数、inject 执行
者、server 级边界、kind 编排归属、回退形态）+ 逐家只读取证清单 + S0-S4 阶段
拆解。**等用户逐条裁决后**：S0 出 ADR + 取证 spike。

**网关路由热装载落地（2026-11-15）**：gateway `routes_source.py`（RoutesSource：
server 契约为真相、文件为启动兜底、最近已知好表保值——TTL 30s 闸 + 后台 15s
节拍刷新，时钟可注入；server 可达即采纳**含空表**=管理面清空如实生效，不可达
保持 server_fallback 好表不回滚文件）+ `ControlClient.fetch_routes`（不可达/
非法返回 None 不猜）；app lifespan 后台刷新任务同步 forwarder.routes，
/health routes 节增 source。真机三态验：文件兜底 → 15s 采纳 server 表 →
清空采纳（40s 越过双闸）→ 恢复。5 项新测试（假时钟），gateway 60 项全绿，
门禁九项绿。M1 陈旧上限 = 15-45s（双闸），单机场景够用。

**CLI claim 账户参数化落地（2026-11-15）**：`claim` 增 `--account/-a`（默认
main，完整卡号 = `<target>:<key>`），领取前号册校验——卡不存在显式红字列
出该应用已有卡（未导入提示先 import），校验失败不触执行；CLI 测试目录首建
（apps/cli/tests，testpaths 收编第 7 目录），5 项 CliRunner 测试（FakeKit +
真连接器注册表，Run 必回/result 可空契约钉死）。遗留项「CLI claim 硬编码
:main」收口。门禁九项绿。

**R4-G6 web 消费落地（2026-11-15）**：设置页增「网关路由」节（A3-01 已收编
四节）——`useGatewayRoutes` composable（装载/整表保存，进入设置页时拉取不进
轮询）+ types 契约派生 + api.ts 网关域端点；编辑器 = 模型名+账户池逗号分隔
行（添加/移除/重置/保存），校验单源在 core（UI 只做表单完整性预处理：全空
行剔除、半空行本地拦下；422 detail 直显）。真机闭环：playwright 走通
「装载回填 gpt-x → 空行保存被剔 → 保存成功文案（含网关重启生效时机）」；
server PUT 落盘数据根 gateway-routes.json 与网关装载同源已验。顺带发现并
纠正：复用 shell 的 BUTLER_* 临时 env 污染了 server 进程，已干净重启。
vue-tsc/build 全绿。

**R4-G6 路由管理面契约落地（2026-11-15）**：路由表校验**单源收进 core**——
`execution/gateway_routes.py`（RouteRule/RouteTable + to_dict/from_dict 对称，
模型重复 = 歧义显式拒绝）+ `GatewayRoutesStore` 端口 + `manage_gateway_routes`
用例（replace 先校验后落盘，非法绝不写盘让网关拒启）；engine 新增
`gateway/routes_file.py`（数据根 gateway-routes.json，原子写 tmp+os.replace，
缺失 = 空表合法态），bridge 装配 `manage_gateway_routes`/`gateway_routes_store`
（`routes_file` kwarg 覆盖）；server 新域模块 `routes/gateway.py`（GET/PUT
/gateway/routes，PUT 非法 422、生效时机=网关重启如实注明），聚合器按序挂载 +
`pnpm gen:sdk` 契约刷新；gateway `routing.py` 瘦身为纯装载（模型 re-export
自 core），**顺修 G5 遗留**：gateway `_build_kit` 裸 `build_engine()` 落 CWD
库 → 改 `build_engine(default_db_path())`。新测试 17 项（core 7 + engine 5 +
server 5），gateway 回归 47 项全绿。门禁九项绿。A2-05 §3/§3.1/§4 已收编。

**R4-G5 双协议面+失败转移落地（2026-11-15）**：`apps/gateway` 新增三模块——
`upstream.py`（ProviderUpstream 端口+注册表，A2-02 §3 插件禁声明式；**真上游
适配器零编造**，取证未回收的 provider 如实 skipped）、`forwarder.py`（转移
编排：循 RouteTable 候选按序重试，5xx/429/connect 转移、401/403 先
pool.invalidate 再转移、其余 4xx 判请求问题不转移原样回传；每尝试 Meter
入账=裁决 7，Meter 失败不打断=台账语义；意外异常冒泡=红线 5）、`proxy.py`
（OpenAI `/v1/chat/completions` + Anthropic `/v1/messages` 双标准面，
require_bearer 挂载，usage 方言解析收敛在协议面，M1 仅非流式——stream 真值
422 显式拒绝，流式取证未回收不猜形状）。lifespan `build_engine` 直装 kit
（裁决 1 进程内直调，`kit_factory` 注入测试），/health 增 proxy 节（surfaces/
adapters/limiter_in_use）。47 项 gateway 测试全绿；真机冒烟：临时数据根起
8123 → 未鉴权 401、鉴权后走完候选循环 502 带逐尝试台账。门禁九项绿。
**真上游接入挂账取证**：trae Windows 运行态请求体/头组/流式（PROTOCOL §9）
→ 适配器按注册表落位；doubao 发测试消息需用户授权。

**butler-feature-dev skill 落地（2026-11-15）**：把已落地功能的分层模式提炼为
项目级 skill `.codebuddy/skills/butler-feature-dev/`（SKILL.md + 5 分册
references + 5 个代码骨架模板 assets）——标准动线 = domain→ports→usecase→
engine 适配器→bridge 装配→server/gateway 端点→web→四层测试→门禁九项→
文档同提交收编；并从既有通用 skill 集合（cross-platform-arch）收编三块：
六边形规约 R1-R9/R7 模型分层、表设计纪律适用子集、门禁验收纪律（SKIP≠PASS、
测试没跑≠通过）。AGENTS.md 路由表已加 skill 入口（第 0 条）。未提交。

**管理台视觉升级 v6 系列落地（2026-11-15）**：对比旧系统（8688）取证后实施
「纸墨 v6」三层视觉锚点（KPI 数字卡/侧栏线性图标/容器轻阴影，token 只动
tokens.css），v6.1 侧栏三层视觉分组（总览/运营/系统，纯视觉层 hash 不变），
v6.2 仪表盘图形化三件套（①近 30 天签到日历条带=ledger 真实 run；②流量卡内嵌
水位条=最低 remaining/total、低水位色只随 core `quota_low` 谓词；③「下次班次」
卡替代「最近一条日志」卡=schedule_times 并集取下一个未来时刻+分钟倒计时）。
裁决补记 DESIGN-DECISIONS D2/D3 + 仪表盘图形化条目；runs 拉取 limit 50→200
（端点上限已支持）。vue-tsc/build/门禁全绿，已提交推送。真机签到批次同日完成
（六连接器领取全过+workbuddy 成功信封修复）。挂账：qoder_cn 401 等用户在
Qoder 客户端人工重登后跑 import+claim 闭环；claude_web 本机无登录态；
chatgpt_web Profile 1 令牌过期。

**R4-G4 Meter+样本表落地（2026-11-15）**：`UsageSample` 增 `duration_ms`（可
缺省）+ model/account 非空校验；`UsageStore` 端口增 `append_sample`/
`list_samples`，engine SqliteUsageStore 实现 **usage_samples 四表**（只增不改
时序事实，ts 倒序读，account 可选全表），db/schema.sql 重新生成（10 表，表数
计数改动态防漂移）；core 新用例 `RecordUsageSample`（usage/usecases/
record_sample.py）——**口径 = 裁决 7**：source 固定 gateway、tokens 读上游
usage 字段缺失 0/0 不猜、duration_ms 记请求时长；落库失败 = 台账语义（审计
留痕 gateway-meter + 返回 False，不打断转发），输入非法显式抛。bridge 装配
`kit.record_usage_sample`。13 项新测试（core meter 8 + engine 样本 5），
门禁九项绿（559 passed）。A2-06 §2/§3/§4 同步收编。

**R4-G3 路由表+限流器落地（2026-11-15）**：`routing.py`（RouteRule/RouteTable/load_routes——
模型→账户池**有序映射即优先级**，M1 精确匹配，失败转移由 G5 调用方按序重试；
校验显式报错：缺 routes 键/空模型/空账户/重复模型/非数组 accounts/坏 JSON
一律 ValueError）+ `limiter.py`（AccountLimiter——每账户 asyncio.Semaphore，
默认并发 1 保守风控优先，overrides 数据覆写，不可重入已写进契约 docstring）；
规则源 = 数据根 `gateway-routes.json`（`BUTLER_GATEWAY_ROUTES_FILE` 覆盖，
缺失=空表合法、非法=**拒启**）；app lifespan 只读装载 + /health 增 routes 节
（rules_file/rule_count/models/account_count）。gateway 26 项测试全绿
（routing 10 + limiter 6 + skeleton 16），真机冒烟：路由装载入 health +
非法文件拒启双证。门禁九项绿（546 passed）。server 管理面（规则 CRUD 契约）
挂账后续批次。

**R4-G2 凭据池落地（2026-11-15）**：`CredentialPool` 端口进 core accounts 域
（ports.py）+ `CachePolicy` kind 数据进 domain.py（未声明 kind = ttl 0 严格
现用现取，保守默认）；实现 `VaultCredentialPool` 落 engine vault/pool.py——
现用现取走 LayeredVault（缺凭据原样上抛），**每次 acquire 全审计**
（gateway-pool：hit/miss/error，miss 叠加 vault.load 自带审计，无未审计读取），
TTL 时钟可注入；bridge 装配 `kit.credential_pool`（build_engine 增
`pool_policies` kwarg，G3 Router/G5 协议面消费）。8 项分册测试全绿
（真 vault+审计+假时钟），A2-04 §3 / A4-01 §4 已同步收编。

**R4-G1 网关进程骨架落地（2026-11-15）**：`apps/gateway` 入 workspace（dist
`butler-gateway`，包 `butler_gateway`，FastAPI+httpx 同 server 栈）——`/health`
健康可观测（uptime/key 指纹/主控可达性 TTL 缓存 30s 惰性刷新）、鉴权 key
启动生成 0600 落数据根（`gateway-auth-key`，重启不换 key，指纹入 health 不泄
key 本体）、主控通信 = HTTP 拉 server `/health`（ADR-012 裁决 2，transport
可注入）；真机冒烟：网关 8100 起停 + key 文件 0600 + 对运行中 server 探测
命中（17.3ms）。9 项 gateway 测试 + 门禁九项绿（全量 521 passed）。
**server/OpenAPI/web 零 diff**（主控通信只读复用既有端点）。

**全库 schema 生成视图落地 + 规范漂移回收（2026-11-15）**：仓库根新增 `db/`
（README + `schema.sql`）+ `scripts/dump_db_schema.py`——临时目录按运行时同款
适配器真实建库 → dump `sqlite_master`，**9 张表 / 5 个索引**按业务域分节（账户/
执行/用量/健康/保管层/审计）；权威单源仍是各域适配器 DDL（A4-01 §5 表按域分置
不变），改表后重跑导出随批提交，新表未登记 `_SECTIONS` 显式报错（防漂移守卫已
实战拦截 3 个用量索引）。同批**回收规范漂移（红线 8）**：A4-01 §5 / A1-02 §6 /
A2-06 §3·§6 的 `usage_samples` 旧说法改为现状三表（快照/汇总 REPLACE、流水
IGNORE 幂等）+ 时序独立表降级为 R 系列方向；A1-05 目录树 db/ 注释校正。

**旧 kit 历史数据迁移准备（2026-11-15）**：勘察结论 = 本机旧库全表 0 行
（kabao/ai-marina 平台目录是 butler 自家前代品牌搬迁链，与 auto-signin-kit
无关），数据源确认为 Windows 侧旧 kit。落地 `scripts/import_legacy_kit.py`
（干跑默认 + 备份 + 幂等 + 行数验证 + 源只读；词汇映射逐词核对入 A0-01 §2.4：
CLAIMED/ALREADY/FAILED 同词直迁、NO_AUTH→EXPIRED、NETWORK→FAILED，无诚实
对应词 status=NULL + verbatim 档案进 params_json.legacy_kit）——合成夹具四步
验证 + server 读路径实测全过。**待 Windows 拷库后真迁**（真迁前停 server）。运行数据仍禁入仓库（数据根规则不动）。

**网页会话多 profile 取证 + 接入（2026-11-14，[ADR-011](adr/ADR-011-网页会话通道每profile一账户.md)）**：
六连接器真机（mac）多 profile 目录形状取证完成、如实登记 A2-02 §9
（trae/qoder/workbuddy 单账号实证、doubao 单实例锁运行态实证、chatgpt_web
双 profile 实存会话令牌）；裁决 = **每 profile 一账户**落地：browser.py 逐 profile
捕获出账户槽（首个凑齐 = main 存量卡位，后续 = 目录名 slug，同目录新旧
布局去重），chatgpt_web/claude_web 通道统一生效，core/server 契约零 diff。
**验收**：门禁九项绿 + 508 tests 全绿（多 profile 槽测试分册
test_browser_profiles.py）。

**六页 IA 阶段二收官（2026-11-14，[ADR-010](adr/ADR-010-六页信息架构.md)）**：
四页（账号/用量/记录/设置）→ **六页（仪表盘/应用/账户/流量/日志/设置）**，
仪表盘默认、待办栏迁入、导入归应用、领取归账户、角标挂仪表盘；重定向表 v2
7 条旧链 + 运行中 hashchange 重写全过（`#/usage`/`#/log` 降级为旧链）；
页名词表 v2 一次到位，主题显示名「纸墨/墨夜/暖纸」与关于节产品名回收阶段一
遗留；`AccountsPage` 485 行 → 页头 76 行 + `MatrixTable.vue` 321 行。
**影响面仅 `apps/web/src/` + 文档**：`api.ts` 零 diff，composables 仅注释/
动作消息换词（数据接口不变），
server/engine/connectors/sdk/mcp/desktop/cli 零 diff，OpenAPI 与
openapi.sha256 零 diff。**验收**：vue-tsc 绿 + 门禁九项绿 + 505 tests 全绿；
浏览器走查 server:8000 + Vite:5173（隔离 BUTLER_DB=/tmp 临时库）——
六页 × 双断点（1440×900 / 375×812）× 三主题（纸墨/墨夜/暖纸）全过，
7 条旧链重定向正确，一键导入（6）与 server apps=6 吻合、
一键领取（0）/角标（无）与 accounts=0/pending=0 吻合，console 零错误；
修掉窄屏顶条六项导航与主名重叠（改两行网格 + 导航横向滚动）。
Butler 重定位六问裁决全部落地。

**按业务域重写 P0-P6 全部完成（2026-11-14，ADR-002）**：`butler_core` 五业务域
+ shared 内核从零落地（端口随域走、依赖恒等式入门禁机检），`butler_engine` 按同
域图重写，旧 `kabao_core/butler_engine` 已删除；全库 six 包/CLI/env/db/存储键/
npm 包名统一 butler（仅 Gitee 远端改名待用户手工）；多账号模型落地
（首账号键 `main` 兼容存量，幂等键按账号，契约 `account_key`/`account_ids`，
一键领取逐账户发起）；一次性迁移集中 `butler_engine/db/migrate.py`（旧库四级
优先级 + vault 旧前缀装配期回写，运行时零 legacy 分支）；OpenAPI 契约已再生成、
web vue-tsc 绿。**验收：全量测试 505 passed + 门禁九项全绿**。
A2-02 §9 如实登记连接器多 profile 取证结论（未取证不虚报）。

## 剩余挂账

- **旧 kit 历史数据真迁待源库**（2026-11-15）：本机旧库 `auto-signin-kit.db`
  全表 0 行（勘察结论：无数据可迁；今晨 00:37 写入仅为 UI 服务只读打开），
  数据源确认为 **Windows 侧旧 kit**——待拷 `data/database/auto-signin-kit.db`
  （含 -wal/-shm）到本机后执行 `scripts/import_legacy_kit.py --source <路径> --commit`
  （脚本已落地并过四步验证：夹具干跑/真迁副本逐行核验/幂等重跑 0 新增/未知
  操作词显式中止；server 读路径 list_recent 35 行无炸，旧 NO_AUTH→EXPIRED
  不触健康连败判定）。真迁前须停 butler server（-wal 非空拒绝）。
- **R3 网页会话通道余项**：Claude 最小 cookie 名单补证（本机无登录态，换环境取证；
  2026-11-14 mac 复核：双 Chrome profile 均无 claude.ai cookie）。
- **npm org 创建** `butler`（网页交互，发布前做；A1-03 §6 口径）。
- **`PRAGMA user_version` 列级迁移机制空悬**（A4-01 §5 既定：随首个真实列级迁移
  落地，无需求不提前实现；`db/migrate.py` 现只做整库搬移，合规）。
- **疑似时间边界测试闪失一次**（2026-11-15：门禁 pytest 曾报 1 failed，复跑即绿；
  候选 = `test_budget_preempts_slow_port` 墙钟断言 `elapsed < 0.4`，余量仅 100ms。
  负载下 7 轮未复现——挂账观察，复现到实锤再修，不无证据弱化断言）。

> mac v10 密文前 16B 段挂账**已闭环**（2026-11-14 真机 528/528，A1-04 §4.1-8）：
> 单条 CBC 链，头 32B = sha256(host_key) 域绑定标签（91 host = 91 seg、跨
> profile 恒定），「16B IV」实为链第二块；前缀切法输出 = 载荷 = cookie 真值；
> `verify_mac_cookie_header` 落地 capture 层完整性校验。

**mac 真机签到调通批次（2026-11-14）**：六连接器真机领取全跑一遍——
trae CLAIMED、doubao ALREADY（CDP 通道真机生效，连签 7 天幂等判定正确）、
workbuddy ALREADY（连签 46 天；**修复 claim 成功信封识别**：上游 code=0/msg=OK
无 credit 字段曾被误判 FAILED——决策表 §3 补行 + 2 测试，复查账本路径生效）；
chatgpt_web 无签到动作（导入+健康卡），真机验证 ADR-011 落榜路径（Profile 1
令牌已被浏览器清理 → 单槽如实）；claude_web 如实未登录。**遗留**：qoder_cn
会话过期（status/usage 双 401，需客户端重登录后重导——外部状态非代码问题）；
CLI `claim` 硬编码 `:main`，多账户卡领取入口待补（当前无实际影响）。

## 下一步（当前焦点）

**R4 G1-G6 已落地（2026-11-15），余项按取证节奏推进**：G5 协议面+转移编排、
G6 路由管理面契约均就绪（Fake 上游端到端验证过），真上游适配器按
`upstream.register_upstream` 落位即可——卡 **Windows 运行态取证**（trae 请求
体/头组/流式形状，PROTOCOL §9；取证不全 = 该 provider 不开工，已由
upstream_not_ready skipped 如实表达）；doubao 发测试消息需用户授权。web 两家
是否纳入反代首版**待用户裁**（plans/02 §3）。可选后续批次：web 路由管理页
消费 /gateway/routes 契约；路由热装载（G5+ 增量，M1 重启生效）。

**R4 网关独立进程：架构裁决完成（ADR-012）+ mac 侧推理通道取证完成（2026-11-14）**：
四家桌面连接器 PROTOCOL §9 已登记——**trae = 反代上游候选一号**
（api.trae.com.cn + llm_raw_chat + x-ide-token + 响应自带 usage 结构 +
check_estimated_balance）；workbuddy = BYO-key 客户端（不适合做上游）；
qoder 域已定路径待网络观察；doubao CDP 驱动可行但发消息属写动作归 G5。
**余项**：trae 请求体/头组/流式形状待 Windows 运行态验证；web 两家是否纳入
反代首版待用户裁（plans/02 §3）。裁决 + 取证回收后按 G1-G6 开工。

> 连接器多 profile 取证**六家全定论**（A2-02 §9，2026-11-14 mac）：桌面四家
> （trae/qoder/doubao/workbuddy）均单账号实证（doubao = app 级单实例锁，
> PROTOCOL §8）；网页两家按 [ADR-011](adr/ADR-011-网页会话通道每profile一账户.md)
> 每 profile 一账户已接入 dock。「应用 → 账户」展开无剩余前置。

## 已定关键决策（不再讨论，照做）

- 前代项目 auto-signin-kit **严禁搬代码**：只提炼 PROTOCOL.md + 行为对照验收（A0-01）
- **ADR-001**：出站适配器独立成 `packages/engine`（COLA infrastructure 正形）；
  端只准 `from butler_engine.bridge import ...`；core.bootstrap 保留纯装配根
- **ADR-004**：from_engine 方言注册表——连接器以**数据**申报业务码→Status 映射、
  加载期注册；默认 legacy 自映射；未知码显式抛 UnknownEngineCode（红线 5），
  用例层转 FAILED + evidence + PROTOCOL_CHANGED；严格字面匹配不归一。
  协议字面量七词（CLAIMED/ALREADY/FAILED/NO_AUTH/PENDING/EXPIRED/SKIPPED）
  与旧系统 oracle 对齐，**永不改名**（两层词汇原则，收编 conventions/3 与 A1-03 §3）
- **ADR-005**：连接器 target 级端口路由
- **ADR-006**：qoder 接入形状 = 声明式扩展（列表领取受限形状 / DPAPI+AES-GCM
  双层凭据 / 机器身份头组 kind 化 / 静默陷阱显式化 = FAILED + repair_hint）
- **ADR-007**：doubao 接入形状 = CDP 界面通道（零凭据）
- **ADR-008**：workbuddy 接入形状 = adapter 端口实现——凭据**现用现取零申报**
  （不落 vault，运行时读客户端会话文件即用即弃）；信封 token 解密走 helper.js
  子进程（客户端自带 Electron runtime；「严禁搬代码」的唯一例外 = 协议契约，
  守卫测试钉 12 标记）
- **M1 硬标准**：每个 Connector 不加特殊分支接入；要写例外 → 停下来改模型
- **kind 收敛原则**（A2-02 §3）：应用接入面 = 声明 + 可枚举 kind 的组合，
  一套运行时 + N 份数据，绝不 per-app 平行代码；协议特殊性只以 kind 形态扩展
- **L0 参数默认值**（core 常量单源）：CREDENTIAL_EXPIRING 预警窗默认 **3 天**
  （`domain/vault.py:EXPIRING_WINDOW_DAYS`）；risk = 连续 **3 次** NO_AUTH
  （`domain/health.py:RISK_NO_AUTH_STREAK`）
- **Windows 凭据管理器（DPAPI）适配器**：ctypes advapi32，纯标准库；系统调用经
  `api_factory` 注入隔离，非 Windows 用假 api 单测（CI 中照跑）
- **Vault 审计不走事件总线**：存/取/轮换在 LayeredVault 内**同步**落审计——
  审计是 R4 反代上线前的安全底线；事件总线只承载通知类事件
- **到期扫描的记忆语义**：凭据/账号都以"上一已知级别"做变更检测——级别不变不重发；
  恢复 healthy 不产新事件类型（A2-01 §5 无恢复事件，不发明），
  账号恢复发 SILENT 级 ACCOUNT_HEALTH_CHANGED 保 UI 同步
- **健康首评语义**：首评即 healthy 不发事件；首评即异常发事件（新事实要进"待处理"）
- **视觉 signal 分类 core 单源**：`ResultKind.signal`（ok/attention/danger/quiet）
  与 `HealthLevel.signal`（ok/notice/attention/danger）——端上染色是业务语义，
  必须 core 出产；UI 只认五词上 CSS class（红线 2 的 Web 端闭环）
- **横幅聚合在端**：横幅句式 = 纯计数 + 文案模板，语义词仍是 core 的 signal——
  属表达不属业务规则；若规则复杂化再上收 core
- **契约流水线口径**：`generate.mjs` 直接 `from server.main import app` 导出
  （免起 uvicorn），hash = `sha256(json.dumps(app.openapi()) + "\n")` 与 verify
  同口径；中间产物 `openapi.json` 进 .gitignore 不入库
- **docs 体系**：设计文档入 specs/ 分层子目录，强制规范入 conventions/
  （00-项目配置为唯一变量入口），决策入 adr/；STATUS.md 代替 TODO.md（避免双源）；
  specs 文件命名 `A{层级}-{NN}{分册字母}-{主题}.md`
- **文件组织与长度**（conventions/4）：一业务域 = 一模块 = 一文件（路由按
  accounts/apps/runs/usage 分域，api.py 纯聚合器）；代码文件软警戒 400 行 /
  **硬上限 600 行门禁机检**（verify 第八项，packages/apps/scripts 下
  py/ts/tsx/vue/js/mjs，gen 等派生物除外；文档不进机检）；
  存量 400+（decl/usecases/dockio）不强制立即拆，新代码不得堆入

## 环境备忘

- 远端 origin = `git@id_gitee_hiclaw520:hiclaw_520/ai-butler.git`（main；
  2026-11-14 远端已由 `ai-kabao` 更名 `ai-butler`；2026-11-16 Windows 机
  remote URL 修正并 ls-remote 验证可达）。
  推送口径（2026-11-12 起 SSH 别名直推）：远端 URL 必须用 `~/.ssh/config`
  别名 `id_gitee_hiclaw520`（hiclaw_520 账号专用钥匙）——裸 `git@gitee.com:`
  走默认钥匙（xiaoyaojiugui 账号）对 hiclaw_520 仓库报 Access denied；
  HTTPS + `credential.helper=manager` 在非交互 shell 弹窗被取消必挂，均弃用
- **uv.lock 口径**：macOS 开发机全局 uv 配置走阿里云镜像，`uv sync` 会把锁源
  重写为镜像——**用 `uv lock --default-index https://pypi.org/simple` 直锁官方源**
  （R1 批①重锁已验证，0 污染）；提交前 `git diff uv.lock | grep -c aliyun` 自检，
  脏了就重出。**2026-11-12 复发实证**：库内旧锁混入 744 行 aliyun（MCP 薄壳批次
  重锁清零）——自检看新增行 `git diff uv.lock | grep -c '^+.*aliyun'` 才准
- **macOS 前端门禁**：系统 node 20 + pnpm 7 打不开 lockfile v9——shell 先
  `eval "$(fnm env --shell zsh)"` 走 node 24 + pnpm 9；apps/web/node_modules
  缺失时报 vue-tsc ENOENT，`pnpm install --frozen-lockfile` 即愈
- pnpm-lock.yaml 已提交，CI 用 `--frozen-lockfile`
- 提交信息规范接入提交钩子三件套 `.githooks/commit-msg` +
  `scripts/install_hooks.py` + `scripts/setup_hooks.cjs`（pnpm postinstall 自动
  启用），规范正文 `conventions/04-提交信息规范.md`。**v2.0.0 严格版（2026-11-12
  起，与 cross-platform-arch skill 同源）**：单号必填（无关联占位 `[0]`），
  超长/句号结尾钩子强制拒绝
- 契约指纹：`generate.mjs` 与 verify 都是
  `sha256(json.dumps(app.openapi()) + "\n")`；改 API 后照常 `pnpm gen:sdk` 即可
- **CodeGraph**（2026-11-11）：CLI 已装 1.5.0-sl.1（npm -g）；前代项目
  auto-signin-kit 已建图；MCP user 级注册 `codegraph serve --mcp --path
  D:/codes/opensoure/auto-signin-kit`；会话内可 CLI `codegraph explore` / `query` 直查
- cross-platform-arch skill 1.8.0 实际位于 **`D:\codes\leisure\leisure_skill\cross-platform-arch`**
  （Windows 端路径；C 盘 ~/codes 不存在）
