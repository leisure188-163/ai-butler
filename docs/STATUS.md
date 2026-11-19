# STATUS · 进度卡（每次会话开始先读我）

> 更新纪律：完成一步就改这张卡。格式固定，方便任何终端的 AI 秒懂现状。
> 最后更新：2026-11-19

**豆包失败留证 + 点击前硬断言（2026-11-19 用户裁决）**：新增 `doubao_cn/evidence.py`（从 adapter 拆出，adapter 596 行仍单文件合规）。①**失败自动留证**——`DOUBAO_FAILURE_CAPTURE`（默认 1）只在「未签→点击」路径装只读旁路，成功即丢弃，判 FAILED 才落现场包 `~/.butler/doubao_failures/`：`stage`（no_button/click_no_flip/detail_error）+ 点击坐标+按钮文本 + `checkin_requests`（页面轨迹筛出的 landing/checkin，**判「平台拒绝」的唯一抓手**）+ 签到区 DOM（含 `topmost_at_click`，判点空/遮挡）+ 页面正文 + 失败时刻完整 detail；签名类走既有脱敏（只存 hash）。判读口诀写进 [PROTOCOL §2.2](../packages/connectors/src/butler_connectors/doubao_cn/PROTOCOL.md)：no_button=界面侧、click_no_flip 有请求=平台拒绝、无请求且 topmost≠「立即签到」=点空。②**点击前身份硬断言**——切号后复核由单读改**连读两次一致**（防刷新瞬时空档误判翻转），并在 `_click_and_confirm` 开头再加一道 `assert_identity`（同样两次），读不到身份按「未知」不放行；任一不过 = PENDING 且本轮零点击（PROTOCOL §9 加固段）。测试：新增 `test_doubao_evidence.py`（5 例：断言三态 + 落证脱敏 + no_button 无请求），connectors 391 passed；门禁九项 PASS。

**凭据分层裁决（2026-11-19，[ADR-029](adr/ADR-029-凭据按账户隔离与会话型平台不抓token.md)）**：用户提议「同步建账户时把该账户的 token 一起抓下来，以后切账户就能拿对应 token，请求都不会出错」。实测凭据面（`acc_account` + `vault_item`）：qoder 三个账户各持 `dpapi_gcm_v10 + umid_cosy`、agentrouter 持 `browser_session`——**token 型平台「每账户一份凭据、切换即取用」已是既有实现**；豆包两账户 / workbuddy / trae 零凭据入库（会话型）。裁决：①token 型维持按 `account_id` 入 vault + 归属校验（取不到显式 `NO_AUTH`，绝不回落"第一份凭据"）；②会话型**明确不做 token/Cookie 抓取**——豆包没有静态 token 可抓（`a_bogus`/`msToken` 由页面 JS 每请求现算），Profile 库运行期独占锁，且裸请求会把会话打到受限态（11-07/08 两次事故、ADR-007/017），抓了只会把"请求不出错"变成"一用就毁"；③任何平台不得以降级裸请求替代缺失凭据。多账户能力对豆包仍是串行（切号→复核→重开活动页）。

**dockio 拆分（2026-11-19，文件长度红线）**：门禁报 `dockio.py` 601 行 > 600（77a8ecd 带入的既存违规）。拆出 [qoder_runtime.py](../packages/connectors/src/butler_connectors/qoder_runtime.py)（`locate_umid` / `registry_install_roots` / `run_runtime_info` / `client_version` / `machine_os` / `hostname` 与三个常量），dockio 保留同名薄包装——`_locate_umid` 把本模块 `_MAC_APP_ROOTS/_MAC_APP_NAMES` 作参数传入，测试的 monkeypatch 面（patch `dockio._MAC_APP_ROOTS` 后仍生效）逐字保持；`_read_machine_id` 留在 dockio（依赖 `expand_storage_path/_glob_dirs`）。dockio 601→467 行。顺带修 `test_unlock_qoder.py` 两个 Keychain 用例：未钉 `sys.platform=darwin` 导致 Windows 上直接撞 `macOS 仅限` 守卫假失败（subprocess 本已 fake，钉平台后各平台同跑）。connectors 386 passed，门禁九项 PASS。

**豆包签到请求样本留档 + 「参数是否拼错」复核（2026-11-19）**：用户再问「是不是我们拼的请求数据完整性不对导致签不上」。真机对照两路：①我们自组的 `detail`（`version_code=23610`）与页面自发（`20800`）返回**逐字段一致**、`code=0`；②11-17 页面旁路快照（`~/.butler/doubao_requests/doubao_requests-2026-11-17.jsonl`，20 条）显示点击后客户端自发的 `POST /alice/ug/campaign/landing/checkin` body `{"scene":"pc_incentive_task_mvp_v3"}`、query 带 `msToken/a_bogus/web_id/tea_uuid`，响应 `710010702`——与我们点击是同一个请求，我们无拼装面。→ 「参数缺项」假设不成立，702 维持既定性（账号级服务侧写路径故障，本地无可修项）；11-19 `Leisure520` 手动点击成功 = 该账号已自愈。新增 [docs/guides/02-豆包签到请求样本.md](guides/02-豆包签到请求样本.md) 留档真实参数、采样方法与判读口诀；`DOUBAO_REQUEST_CAPTURE` 维持默认关（仅取证时临时开）。**已签态样本补录（同日 09:33）**：抓活跃账户完整 `detail`（code=0、`checked_in_today=true`、`continuous_days=2`、`progress.total_amount=4950`、8 tasks）落本地 `data/doubao_samples/`（目录入 .gitignore，含昵称/邀请码不入库）；同时取证「已签态无『立即签到』按钮、签到区只有 `每日签到+200 额度` 大卡」——`_BUTTON_TEXTS` 精确匹配只在未签态命中，已签态找不到按钮是预期而非故障，该判读已写进 02 文档 §6。

**只读采集不再抢焦点（2026-11-18，[ADR-028](adr/ADR-028-只读采集不产生界面动作.md)）**：用户反馈平台行「刷新」（已接入后由「接入」变来）会把豆包客户端窗口弹到前台。真凶：`POST /platforms/{target}/import` 导入后顺带 `collect_usage`，豆包用量取 Cookie 时无活动页则 `open_activity`（`Target.createTarget`）在客户端新开页面 → 窗口置前。修复：`cdp.py` 新增浏览器级 `storage_cookies(domain)`（`Storage.getCookies` + `/json/version` 的 `webSocketDebuggerUrl`，按域过滤）；`doubao_cn/usage.py` 改走它，删 `pick_activity_target`/`open_activity` 分支，取不到 Cookie 显式报错；导入顺带采集语义保留。**实测**：5 个平台 `POST /platforms/{id}/import` 前后前台应用不变；`POST /usage/collect` 9222 targets 12→12、前台不变；真机 `storage_cookies('doubao.com')` 34 条（全量 53）。测试：doubao usage 8 passed（新增「绝不建页」「空 Cookie 显式报错」）+ cdp 13 passed（`storage_cookies` 两用例）。红线 8 同批：ADR-028 + doubao PROTOCOL §7.2 Cookie 来源 + A2-02 §11 + 本条。

**Qoder mac 解锁链修复（2026-11-18）**：dock 报「Keychain 未取到 'Qoder Platform Safe Storage'」。真机取证（dump-keychain 元数据）本机 Keychain 仅 `Qoder App Safe Storage` 一条（acct `Qoder App Key`）——qoder PROTOCOL §1 的实测定稿本就是它，unlock.py 常量错名（与 workbuddy `.platform` 同性质的代码/取证记录打架）。修复两处：①[unlock.py](../packages/connectors/src/butler_connectors/unlock.py) 服务名改候选序（`Qoder App Safe Storage` → `Qoder Platform Safe Storage`，第一命中即用，`macos_safe_storage_password` 支持显式 service 覆盖）；Global `com.qoder.app.stable/auth.v1.dat`（547B v10/CBC）用该钥匙端到端解通（token + refreshToken/expiresAt 全键，首读有 Keychain 授权弹窗）。②[dockio.py](../packages/connectors/src/butler_connectors/dockio.py) runtime-info 定位 `_MAC_APP_NAMES` 加 `.app` 形态（`Qoder.app`/`Qoder CN.app` 与 `.platform` 旧形态双兼容，与 workbuddy 同因——本机装的是 `Qoder.app`，arm64 runtime-info 实跑通过）。真机复验：`butler import qoder_cn` → `✔ 已导入 qoder_cn:global-699e39eb`（healthy，kinds = dpapi_gcm_v10 + umid_cosy）、`butler claim qoder_cn --account global-699e39eb` → `ALREADY`。附注：`butler claim qoder_cn` 缺省仍命中旧 `qoder_cn:main`（risk/已撤销）卡——缺省取「第一张卡」按创建序，指定 `--account global-699e39eb` 即可；测试 373 passed（unlock 新增候选序 2 用例）。PROTOCOL §1 已补 Global mac 复核两条。

**WorkBuddy 昵称编址（ADR-025 扩展，2026-11-18）**：用户问「为什么 workbuddy 还在用 main 占位」——查明 ADR-025 排除项写明 workbuddy 属「无身份来源平台」，但真机核实 `account.nickname` 实为加密信封（168 字符 envelope，与 accessToken 同链），排除前提不成立。扩展实施：①helper.js 加可选 `expect:"field"` 分支（跳过明文 token 字符集校验，缺省路径逐字节兼容，reply 形状不变）；②session.py 拆出共享解密循环 `_decrypt_via` + 新增 `decrypt_field`（只校验非空 ≤32768），`decrypt_envelope` 保持 token 契约；③dock 体检四项后追加本地只读身份解密——`account_code=昵称`、`account_name="WorkBuddy CN · 昵称"`，解密失败不阻塞 dock（默认 main + issues 如实记 note，红线 5）；④存量一次性迁移 `workbuddy_cn:main → workbuddy_cn:大海`（acc_account + usage_snapshot 38 行；exe_claim/audit_log 台账审计保留旧 id；迁移前备份 `/tmp/butler-backup-pre-wb-nickname-20261118-214353.db`）。真机复验：CLI import → `workbuddy_cn:大海`、claim → ALREADY（+100 连签 49）、API `POST /platforms/workbuddy_cn/import` → `accounts:["workbuddy_cn:大海"], issues:[]`。workbuddy 四测试套 79 passed（dock 新增 4 用例：明文昵称/信封解密/解密失败回退/缺失默认）。红线 8 同批收编：ADR-025 排除项修订（workbuddy 移出）+ ADR-008 决策 2/4 v1.1 修订 + workbuddy PROTOCOL §1 helper 契约与 dock 落账身份两行 + 本条。

**WorkBuddy mac runtime 定位修复（2026-11-18）**：真机 dock 报「凭据为加密信封但未定位到客户端 runtime（mac 解锁链待真机取证）」。查明代码 `_MAC_APP_NAMES` 写死 `WorkBuddy.platform` / `WorkBuddyAI.platform`，而本机与 PROTOCOL §1 记录的实测形态均为 `.app`（`/Applications/WorkBuddy.app`，bundle id `com.tencent.workbuddy.mac`，主程序 `Contents/MacOS/Electron`）——代码注释与 PROTOCOL 记录自相矛盾，属代码抄错。修复：`_MAC_APP_NAMES` 改 `.app` 形态，测试 5 处同步（test_workbuddy_localenv.py）。**顺带修掉 import 全阻塞的存量 DB 残留**：`~/Library/Application Support/butler/butler.db` 里 `plat_platform__reorder` 是上次中断迁移留下的——**5 行真实数据在其中、`plat_platform` 为空**（RENAME 后、拷贝前被打断），反向恢复（DROP 空表 + RENAME 回原名）后迁移正常走完；改表前备份 `/tmp/butler-backup-before-reorder-fix.db`。真机复验：`butler import workbuddy_cn` ✔、`butler claim workbuddy_cn` → `ALREADY`（今日 +100，连签 49 天，累计 4900）——mac 解密链端到端通。注：WorkBuddy 凭据零 vault 入库（ADR-008 决策 3），不出现在 `cards list` 属设计使然。

**外链打开方式修复（2026-11-18，[ADR-027](adr/ADR-027-外链交系统默认浏览器.md)）**：用户反馈设置页点链接「没跳系统默认浏览器」。查明两处根因：①接口文档写死 `http://127.0.0.1:8000/docs`（换端口/桌面 sidecar 随机端口即指错）；②Electron 壳无外链策略，`target="_blank"` 被开成壳内窗口。修复：`utils.docsUrl()` 按 `window.location.origin + /docs` 同源派生（vite dev 代理 `/docs` + `/openapi.json`）；`apps/desktop/main.js` 加 `setWindowOpenHandler`（deny + `shell.openExternal`）+ `will-navigate` 跨源拦截，只放行 http(s)，同源导航留壳内。**边界如实**：纯浏览器打开的 web 无法指定用哪个浏览器开新标签（浏览器/OS 层行为），要"跳出系统默认浏览器"须走桌面壳。vue-tsc 0 错误。

**AgentRouter 端口归属修复（2026-11-18，[ADR-026](adr/ADR-026-调试端口归属校验与连接器端口可配置.md)）**：平台页「导入」会把 AgentRouter 页面开进豆包客户端窗口（9222 被豆包占用，agentrouter 适配器写死该端口；「导入全部」按编码排序又把它排第一）。修复：①agentrouter 端口改 `AGENTROUTER_CDP_PORT` 可覆盖（缺省 9222 仅兼容旧契约，非法值显式报错不静默回退）；②`web_ui` 新增 `require_browser_port` 归属校验——页面 target 出现客户端私有 scheme（`doubao://` 等）即 `PortNotBrowser`，适配器转 `BrowserPortError`，**不往客户端窗口开页**；③`run()` 端口不可用 = FAILED（不误转 relogin 待办），dock 如实进 issues 由导入结果展示。测试：新增 14 用例（agentrouter 9 / web_ui 5），connectors 全绿；PROTOCOL §4/§5 + A2-02 §10 同批收编。

**账户编址实际昵称化（2026-11-18，[ADR-025](adr/ADR-025-账户编址用实际昵称.md)）**：用户裁决同步账户信息不再用 main/派生占位，编址用实际昵称。`resolve_account_key` 改昵称优先（基线/登记簿命中 → 昵称，缺失才 sec_uid 派生兜底）；`resolve_target_identity` 删 main 字面量特判（基线与其他账户同按 code 匹配）；dock 落账显式传 `account_code=昵称` + `account_name="Doubao CN · 昵称"`（主账户登记移到身份采集之后）；usage 守卫活跃 key 同口径；CLI `--account` 省略 = 该平台第一张卡。存量一次性迁移：`doubao_cn:main → doubao_cn:逍遥酒鬼`、`doubao_cn:u66b1e22d → doubao_cn:Leisure520`（含 usage_quota_ledger 60 行引用；exe_claim 台账历史保留旧 id，审计不可改；迁移前 DB 快照备份）。真机复验：import 输出 `doubao_cn:逍遥酒鬼` + `doubao_cn:Leisure520`，登记簿 account_code 刷新为 Leisure520，幂等无重复卡。connectors 测试 364 passed（3 文件编址断言对齐）。PROTOCOL §5 收编 + core `account_code="main"` 默认值保留（无身份来源平台兜底，ADR-025 排除项）。

**自定义平台（2026-11-18）**：把"平台能否自己新建"落成**能真跑的自定义连接器**（而不是一行死记录）。内置清单之外的网站由用户在平台页「＋ 自定义平台」填 4 件人话的事（编码/名称/登录域名/登录态 cookie 名）+ 状态查询 + 领取请求 + 判定方式 + 调度时间，server 渲染成与内置同构的 `manifest.yaml + declarative/{provision.run,session.import}.yaml`，落 `%APPDATA%\butler\connectors`（`BUTLER_CUSTOM_CONNECTORS` 可覆盖），交给同一套 `DeclarativeProvisionPort` 执行——排班、凭据、台账、事件全部沿用。能力边界：自定义目录**只允许 declarative**（adapter = 任意代码装载，装载期拒绝）、`entry` 不许越界、与内置 id 撞车拒绝；落盘前先在临时目录完整装载一遍，坏声明不写正式目录。热加载：`reload_connectors()` 重装端口（replace=True）→ 名册同步 → 调度重排；删除后名册自动 deprecated、台账保留。端 = `GET/POST /platforms/custom` + `DELETE /platforms/custom/{code}`（409 内置占用 / 422 声明不完整 / 404 不存在）；web = 内联表单 `CustomPlatformForm.vue` + 编码列「自定义」徽 + 操作列「删除」。真机验证：POST 落盘 → 名册出现（capabilities `provision.run+session.import`、credential `browser_cookie`、kind web）→ DELETE → 名册回到 5 家、二次删 404。新增测试 11（connectors 装载/拒绝/越界/删除）+ 6（server 端到端），门禁九项 PASS。

**术语统一 App + accounts 表 v2（2026-11-17，[ADR-018](adr/ADR-018-术语统一App与accounts表v2.md)）**：用户裁决退役 provider 术语，全库统一 **App/应用**（列 `app`、端口 `list_by_app`、DTO `AccountOut/RadarAccountOut.app`、领域类 `App`；`key_provider` 解密参数与第三方 LLM provider 等外部机制描述保留）；词表收编 A1-03 §3，生效 spec（A2-01..04/A1-02/A1-05/conventions-02）同批回收。**accounts 表 v2**：显式 `account_key` + `UNIQUE(app, account_key)` 兜底不变量，补 `base_url`（Qoder 双 host 事实落库）/`device_ref`/`entitlement_json`（Entitlement 首次落库）/`enabled`（调度 tick 跳过停用账户，与 health 熔断正交）/`deleted_at`（软删除落库）/`updated_at`（统一审计字段 id/created_at/updated_at 本表先行，其余域分批）；老库自迁移幂等（RENAME + ALTER 增量 + 回填）。SDK 重生成 + web 三组件同步，`vue-tsc` PASS；dump 脚本登记新索引后防漂移守卫按预期拦截并放行；全量 pytest 711 passed / 10 skipped。dump 分域视图刷新（accounts.sql 1 表 / 2 索引）。

**schema 生成视图按业务域拆分（2026-11-17）**：用户裁决 `butler-schema.sql` 单一全量文件拆成每域一个——`dump_db_schema.py` 改为按 `_SECTIONS`（对象→域 key）+ `_DOMAIN_FILES`（域→文件名）输出 `data/sql/{accounts,execution,usage,health,vault,audit}.sql`，废弃全量文件（README 收录新清单与 `cat data/sql/*.sql` 兜底口径）；conventions/00 §数据根行同步收编。守卫升级：未知对象报错不变，新增「登记域无对象」也报错（红线 5）。**顺带修掉一处漂移**：vault 撤销能力加列（`vault_items.revoked_at/revoked_reason`）时未重跑 dump，旧全量视图缺这两列——本次重新生成补齐。无代码行为变化，纯生成视图与文档收编（红线 8）。

**豆包全链路零裸请求落地（2026-11-17 深夜，[ADR-017](adr/ADR-017-doubao-detail改页面上下文fetch全链路零裸请求.md)）**：旧 kit NOTE-04 §4.3 机理（裸 HTTP 缺签名 → 会话受限 → 反复裸请求升级账号级）+ 11-16/17 双机 spike 实证（活动页上下文注入 fetch 被客户端网络栈自动补 `msToken`/`a_bogus`，detail `code=0`）→ detail 只读由裸 httpx POST 改**活动页上下文 fetch**（浏览器原生 Cookie/Origin/Referer/UA + 自动补签，连接器只拼 query/body）。连接器零凭据处理面（`Network.getCookies` 现取路径删除）、`usage.py`（M2 未投产）不在本条范围；`record_detail` 快照退役（capture=1 时页面旁路连带记录 detail fetch）。非 2xx 语义保持（哨兵键回传）。测试 27 adapter + 2 snapshot + 17 switch 全绿，全量 711 passed / 10 skipped（对照改前基线 712/10：唯一 -1 = 按计划删除的 record_detail 用例）。PROTOCOL §1.2/§2/§2.1/§6/§7.3 收编 + ADR-007 决策 3 与风险敞口两条回收（红线 8）。**账号处置不变**：702 停点，等明天调度自然复验一次；全链路裸请求诱因已清零，等平台自愈/账号反馈。

**豆包 702 定性收官 + 页面旁路默认关闭（2026-11-17 晚）**：用户报「签到失败，请稍后重试」疑我们改坏请求参数。CDP Network 域零污染取证（浏览器级 ws + flatten attach + `Network.enable`，页面 JS 不可见；旁听与真实 claim 并行，capture=OFF）抓到客户端自发 checkin 全量现场：query 带 `msToken(168)/a_bogus(188)/web_id/tea_uuid`（`device_id` 空值——detail 同空照常受理），响应 HTTP 200 `{"code":710010702,"msg":"系统错误"}`；同会话页面自身 `v3/detail` 200 满数据。结论：**702 非参数缺项、非签名失效**——同参数 detail 受理 + 另一账户同机 08:46 成功 + Windows 同账号同败 → 账号级服务侧状态；「卸载重装恢复」= 重装重置设备身份与登录态（假说，待复验）。我们唯一自组的 detail（派生 version_code=23608 vs 客户端自发 20800）只读且 code=0——非肇因，记保真缺口。修复：`DOUBAO_REQUEST_CAPTURE` 默认 "1"→"0"（页面 fetch/XHR 猴补在字节反爬页禁用于生产 run；取证改 CDP Network 域旁听）；PROTOCOL §2.1 收编现场样本与方法。**重装对照复验（同日 20:56）**：全卸载重装 2.36.8 + 新登录（设备身份确已重置：tea_uuid 16→19 位、msToken 168→184），dock 带端口重启 + 身份基线复核 PASS（**sec_uid 账号级稳定，跨重装不变——身份簿机制经受重装考验**）；干净 claim（零注入、单次点击）仍 FAILED：checkin `710010702「系统错误」`、detail code=0。**「卸载重装恢复」假说被证伪**——702 定性升级：账号级服务侧写路径故障（同机他号成功 / 异机同号同败 / 重装不复位，三证据收敛）。处置：停点等自愈 / 手机端旁证 / 账号侧反馈；本地无可修项。

**Qoder 多账户（CN + Global）补全（2026-11-17）**：真机确认 Windows 有两个真实
Qoder 账户来源——`%APPDATA%\com.qodercn.app.stable`（CN，user
`019ffa59-7821-7f3b-a430-94af21a7150f`，host `openapi.qoder.com.cn`）与
`%APPDATA%\com.qoder.app.stable`（Global，user
`01a1cae7-3b32-70bb-8efc-bffb61f0db1f`，host `openapi.qoder.sh`）；同一 token
跨 host 均 401 `TOKEN_EXPIRE`，只能各用各的 host。原 `qoder_cn` 只扫首个
`auth.v1.dat`、固定 `qoder_cn:main`，Global 从未进卡。改造：①`dockio` 逐目录
枚举 profile，同一 user id 去重，CN 首账户保留 `main`，Global 用
`global-<sha1(user.id)[:8]>`；②`AuthSpec.base_urls` + `account_base_url()` 按
账户切 CN/Global 基址，provision 与 usage 共用；③声明式 YAML 增加
`%APPDATA%/com.qoder.app*` 与 `{base_url}` 模板。**真机验证**：dock 产出
`qoder_cn:main` + `qoder_cn:global-020dbc5a` 两张卡；2026-11-17 CN status
`ALREADY`，Global status 发现 1 项待领 → 逐项 claim → status 复查 `CLAIMED`
（双账户 claim 写入路径首次跑通）；server `POST /api/v1/apps/qoder_cn/import`
返回两张卡、`POST /api/v1/runs` 两账户均 `ALREADY`。新增 dock 双 profile/去重、
decl 基址切换、usage Global host 测试；`pytest -q` 717 passed / 2 skipped，
`verify_project.py --project . --test` 九项 PASS。**补充取证（同日）**：
两目录 `auth-profile-overlays.v1.dat` 已解密——均为 `schemaVersion=1`、
`profiles={}`、仅一条 `nicknameMigrations`；两 `main.sqlite.account_profiles`
均 0 行，全库 distinct 登录 user id 仍只有上述 CN/Global 两个。结论：本机 Qoder
客户端当前只保留“每个产品域一份”登录态，系统能看到并自动签到的真实账户就是
这两个；用户若还有更多 Qoder 账户，其凭据不在本机这两个数据目录里，需另行
提供来源（浏览器会话、其他设备或手工 token），不能凭空生成。
**同日补丁**：`dockio` 在给 CN profile 分配 key 前先解密已有 `:main` 卡的
user id；只有同一 user id 才继续用 `main`，切换后的新 CN 账户改用
`cn-<sha1(user.id)[:8]>` 新增，旧主卡不再被覆盖。这样用户逐个登录并导入时，
历史账户会累积而不是互相替换（仍不能发现从未在本机登录过的账户）。
**重启后真机复验**：当前 Global 登录已切到 `Leisure520@sina`，`POST
/api/v1/apps/qoder_cn/import` 新增 `qoder_cn:global-699e39eb`，旧
`qoder_cn:global-020dbc5a` 仍在；`GET /apps` 现返回 3 个 Qoder 账户
（`main`、`global-020dbc5a`、`global-699e39eb`）。三个账户 `POST /runs`
均 `ALREADY`。这证明同一数据目录换号后可以累积账户，而不是覆盖。
**应用页同步入口（2026-11-17）**：`AppsPage` 新增「同步全部」和每行「同步」；
已导入应用也会重新执行 `/apps/{target}/import`，捕获客户端当前登录态并按稳定
key 追加账户，不再只有未导入时才能点到「导入」。
**账户关联修正（2026-11-17）**：账户页不再用 `AppOut.account_id`（仅排序首账户）
判断归属，改为按 `account.provider` 对应 `AppOut.id`，并以 `account_ids` 兜底；
同一应用的第 2、第 3 个账户不会再显示为“未关联应用”。

**豆包双账户登记补齐与切号复测（2026-11-17）**：Windows 真机发现两个真实缺口并修复：
①`save_identity_registry` 在单会话采集只返回当前账户时会把 `others` 重写空，用户切过号后
第二张卡会消失——改为合并保留既有登记；②`adapter.dock` 只登记当前活跃身份，登记簿里的
非活跃账户不会进卡包——改为把 `others` 一并补登。当前 Windows 已导入
`doubao_cn:main`（逍遥酒鬼）+ `doubao_cn:u66b1e22d`（Leisure520），身份簿
`~/.butler/doubao_identity.json` 已合并（备份 `.bak-20261117`），`data/doubao_identity.json`
保持仓库既有双账户记录。验证：`test_doubao_switch.py` 17 + `test_doubao_adapter.py` 27 +
`test_doubao_snapshot.py` 3 = **47 passed**（新增请求快照 3 项）。**切号真机仍不成立**：当前客户端（2.36.8）账户仍是逍遥酒鬼（重载 chat 页后
localStorage 与左下 chip 都未变）；ArrowDown 能把焦点走到 Leisure520，但
Enter/Space/受信任点击都只关闭菜单、45s 内身份不翻转；`onSelect` 为空、
`onClick` 只收起弹层，疑似客户端未接切号回调。`claim main` 仍
`FAILED`（702）；`claim u66b1e22d` 为 `PENDING`（自动切号失败，提示人工切换后重试）。
**不把 702 误报登录过期**：702 仍按平台/会话侧 `FAILED`，登录过期走 `710012001` →
`NO_AUTH` + relogin；桌面客户端“退出登录/重登”维持人工边界（ADR-015/016）。

## 一句话现状

**页名词 v3（2026-11-18）**：侧栏六项升级为管理台口径——仪表盘 / 平台管理 /
账户管理 / 用量管理 / 运行日志 / 系统设置（用户裁决：平台→平台管理，其余相应改）。
PageName 与页面 h1 同步，英文 hash 不变（dashboard/platforms/accounts/traffic/
logs/settings），legacy 别名表覆盖 relay/usage/log 等旧直链静默重写；
QuickPanel 快捷片、TodoRail/平台页的「去账户」跳转、Dashboard/Traffic/MatrixTable
引导文案全部对齐。词表 A1-03 与 A3-01 六页 IA 同批收编。

**平台类型 + 列序校正（2026-11-18）**：plat_platform 增 platform_kind
（web=网页版 / client=本机客户端，manifest 必填，core PLATFORM_KINDS 校验），
列序 platform_name → platform_kind → client_version → capabilities。
同时修掉"client_version 物理列序落到末尾"：SQLite ADD COLUMN 只能追加，老库
补列后按 DDL 权威序重建表整表拷回（幂等零丢失，_reorder_columns）；
06-SQL规范新增列序纪律节。端侧 PlatformOut 增 kind/client_version，平台页
展示类型徽与版本。真机：agentrouter=web、其余=client、doubao_cn v2.36.8。

**前端应用→平台同步（2026-11-18）**：导航/PageName 早前已改「平台」，但页面
标题、表头、空态、QuickPanel/Dashboard/Traffic/Log 文案、组件与页面文件名
（AppsPage→PlatformsPage、AppBadge→PlatformBadge）、api 函数
（getApps/importApp/importAllApps→getPlatforms/importPlatform/importAllPlatforms）
仍留「应用」旧称，已全量同步；server 路由注释、CLI 表头、A1-03 词表与 A3-01
六页 IA 同批收编（词表口径：app→platform 为退役禁用词，ADR-019）。

**平台册 client_version（2026-11-18）**：plat_platform 增 client_version
（列序在 capabilities 之前），组合根同步名册时经 provision 端口
`read_client_version()` 只读探测（豆包=Info.plist 2.36.8；探不到/网页平台
落 ''=未知）。坑：hook 必须挂在 provision 端口实例（DoubaoCdpProvisionPort）
上而不是 manifest 描述对象和 _Butler 工厂上，否则组合根取不到。老库幂等
补列（plat_cols 非空守卫，空库跳过）。真机验证 doubao_cn=2.36.8。

**真库首启修复 + 豆包 .app 形态（2026-11-18）**：两处真机才暴露的问题——
① accounts 适配器 __init__ 建表先于迁移，老库（有 accounts 表）首启
RENAME 撞名（顺序反了，空测试库测不出），改为迁移先行；② 豆包安装形态
写死 Doubao.platform，真机是 Doubao.app（2.36.8），版本/主程序/进程匹配
改双形态探测。另发现默认库路径分叉（平台根 vs 项目内 data/database，
BUTLER_DB 指定项目内为主库）与旧库半迁移损伤（已修复保留，备份
butler-db-fix-backup-20261118.db）。真机验证：豆包双账户导入 issues=[]，
签到链路 ALREADY（detail 权威判定）。门禁九项 PASS。

**exe_run 改领取记录 exe_claim（2026-11-17，ADR-024）**：领积分/领 token
语义统一为「领取」，表 exe_claim（代理键 + run_id 业务键 UNIQUE + 审计三件，
幂等回放 ON CONFLICT(run_id) 只刷 updated_at）；老库迁移链 runs → exe_run →
exe_claim 幂等零丢失；端侧 /runs 契约与 core Run 术语保留，SDK/前端零改动。
测试 **715 passed + 10 skipped**。

**分域产物文件名对齐表名前缀（2026-11-17）**：data/sql/ 下文件名
= 表名域前缀——accounts.sql→acc.sql、platforms.sql→plat.sql、
execution.sql→exe.sql（usage/health/vault/audit 本就同名）；
dump 脚本 _SECTIONS/_DOMAIN_FILES 同步，06-SQL规范/A2-04/A2-09 收编。

**名册收编扫尾（2026-11-17）**：DB 名册为真相源的最后落实——CLI
`butler platform platforms`、server `import-all`、`claim-all` 三处"选谁"
逻辑全部改读 plat_platform 名册（删除穿 connectors registry 拼装的编排代码），
registry 只留运行时分发（dock/预算/时间表解码）；import-all 目标按
platform_code 排序定序；词表 v2 退役词（泊位/卡位/停靠/卡包）注释全量清理。
测试 **715 passed + 10 skipped**（test_data_root 存在顺序偶发 flake，单跑即绿）。

**SQL 规范成文（2026-11-17）**：历次数据层裁决收编为
`docs/conventions/06-SQL规范.md`（表名域前缀/审计三件/关键字禁用/
显示列业务命名/code 化/幂等自迁移/不删行/分域产物），规范索引与
AGENTS.md 路由同步。

**platforms 独立第六业务域（2026-11-17，ADR-022，修正 ADR-021 托管方案）**：
平台被账户/调度/执行多域引用，独立成域——core 新增 `butler_core/platforms/`
三件套（PlatformEntry / PlatformRepository / SyncPlatforms），engine 新增
`butler_engine/platforms/sqlite.py`；表 `acc_platform` → `plat_platform`
（RENAME 幂等自迁移），分域 schema 产物新增 `platforms.sql`；域图五域 →
六域（A1-05/A1-02/A2-01/AGENTS/README 同步），A2-04 §2.2 平台册节回收进
新分册 A2-09。端侧 `/platforms` 契约与路由零改动。显示名称列命名收编（ADR-023）：
plat_platform `display_name` → `platform_name`（自迁移），A2-04 残留
`display_name` 更正为 `account_name`；分域 schema 产物 `platforms.sql`
同步重生成。测试 **715 passed + 10 skipped**。

**表名域前缀统一 + 平台落册（2026-11-17，ADR-021）**：全库 11 张表改
「域缩写前缀 + 单数实体」——acc_account / acc_platform / exe_run /
usage_snapshot / usage_aggregate / usage_quota_ledger / usage_sample /
health_state / vault_item / vault_history / audit_log（索引随名，老表
RENAME 幂等自迁移零丢失）。平台不再只活在内存 Registry：新增 acc_platform
表（账户域托管），启动时 manifest 事实经 SyncPlatforms 用例 UPSERT 落册、
缺失平台落 deprecated 不删行、is_active 用户开关；`/platforms` 名册改读
名册表 + 台账并账，删除穿连接器包拼装逻辑；`/platforms` 契约形状不变
（SDK/web 零改动）。测试 **715 passed + 10 skipped**。

**accounts 列名 code 化（2026-11-17，ADR-020）**：账户域三列再改名
`account_key`→`account_code`、`platform`→`platform_code`、`display_name`→
`account_name`（概念术语「平台/Platform」不变，仅列/字段/契约同步）；索引改
`uq_accounts_platform_code_key` + `idx_accounts_platform_code`；v3 早期形状走
RENAME COLUMN 自迁移；AccountOut/usage 契约字段与 SDK、web 同步重生成。
测试 **711 passed + 10 skipped**。

**术语 platform 统一 + accounts 表 v3（2026-11-17，ADR-019）**：全库 app→platform
（连接器家族 ConnectorPlatform、accounts.platform 列、server 路由 `/platforms`、
PlatformOut 契约、SDK 重生成、web 页名「平台」；保留 FastAPI 实例变量 `app`、
AppBadge、`AppsPage.vue` 文件名、scheduling `Trigger.enabled`、第三方 LLM provider）。
accounts 表 v3：每表 `id INTEGER PRIMARY KEY AUTOINCREMENT` 代理键，规范 id
`{platform}:{account_code}` 降级为 `account_id` UNIQUE 业务键（编址不变），`enabled`→
`is_active`（数据库关键字规避），save 用 UPSERT 保代理键不漂移；v1/v2 老库重建式
迁移零丢失。全库 DDL 约定（代理键 + created_at/updated_at 必备 + 禁用关键字列名）
收编 A4-01 §5；A2-04 §2.1 升 v3、A1-03 词表、A3-01 页名同步。测试 **711 passed +
10 skipped**。

**AgentRouter 接入 + 通用网页状态底座（2026-11-16）**：新增 `butler_connectors/web_ui.py`
（CDP 只读页面 `localStorage.user` 非密字段，找不到页面/未登录抛 `WebPageUnavailable`，
不读 token/cookie）；页面关闭时由 2026-11-17 补丁自动打开 `/console`，不再直接判“未打开”
与 `agentrouter` adapter 连接器。真机取证：AgentRouter（New API，
`ps.air-outer.com`）**登录即签到**——登录成功发 $25，无独立 `/api/user/checkin`（POST 404、
普通用户 GET 权限不足，模型 API key 不适用 dashboard 路由）。连接器 `provision.run` 读页面
`checked_in`：true → `ALREADY`，false → 自动「退出 → GitHub 登录 → 回调 host 换为
ps.air-outer.com」→ `CLAIMED`（登录即签到）；页面在登录页/localStorage 无用户时也尝试
`force_login` 自动回登录；GitHub 会话也失效才 `NO_AUTH` + `relogin`。凭据只存 `browser_session` 非密定位
`{domain,port,user_id}`。已重启主控、`/apps` 出现 `agentrouter`、import 登记
`agentrouter:main`（显示名 `AgentRouter（github_437667）`），`POST /runs` 返回 `ALREADY`
（证据 `checked_in=true`，用户 id 437667）。`claim-all` 中 agentrouter/doubao/trae/workbuddy
均通过，qoder 仍 `NO_AUTH`（本地凭据已撤销，见下条）。ChatGPT/Claude 网页连接器改
`retired: true`（代码保留审计/回滚，账户/历史已清），不再出现在 `/apps` 与一键导入；
`/apps` 现只剩 agentrouter/doubao/qoder/trae/workbuddy。纯签到连接器
agentrouter 没有 usage 端口，import 不再把“无额度可采”报成 issue（2026-11-17）。站点
`checked_in` 每日 00:00 重置，调度已改为 **`00:05` 主触发 + `09:05` 兜底**；真机
`_relogin()` 已验证自动退出/回调前缀替换后回到 `checked_in=true`。2026-11-17 复验：
页面关闭时自动打开 `/console`，GitHub 重登后 `checked_in=true`，import 返回
`agentrouter:main`、`issues=[]`，`POST /runs` 为 `ALREADY`；全量
**684 passed + 10 skipped**。

**登录态失效四段闭环（2026-11-16，[ADR-015](adr/ADR-015-登录态失效必须可见可修并停止自动重试.md)）**：qoder `HTTP 401` 原被记 `FAILED`——不进待办、无修复提示、每班次重打。①**归类**：`TransportError.status_code` + `AuthSpec.reauth_status_codes`（trae/qoder 申报 401/403）→ `NO_AUTH` + `RepairHint(action_id=relogin)`；未申报码仍 `FAILED`。②**可见**：`expired/invalid` 严重度 BADGE→PUSH；动作落地后立即评估健康；新增 `SystemChannel`（macOS `osascript` / Linux `notify-send`，server `BUTLER_SYSTEM_NOTIFY` 默认开、测试关；投递失败入日志，不假装送达）。③**可修**：`/pending` 带 `repair_reason/repair_action_id`；TodoRail 行内「重新登录 → 我已登录，立即重试」（`POST /runs` 带 `account_id`）；待办聚合改为每个 (kind,target,account) 只看最新结果，修好后旧失败自动让位。④**熔断**：`CheckinSchedule` 注入 `assess_health`，`invalid/expired/risk` 跳过自动触发，每窗口只记一条日志；手动重试不受限。**明确不做**自动清客户端会话/强制登出（桌面登录态在客户端，清库只会丢证据；登录不自动化 ADR-007）；butler 自己的本地副本撤销按 [ADR-016](adr/ADR-016-失效凭据只撤销管家本地副本.md)。**实测**：重启后 qoder 重试返回 `NO_AUTH`（证据「鉴权被拒（HTTP 401）——登录态已失效」，pending 带 `relogin`），账户健康 `invalid`。测试四包 **591 passed + 10 skipped**，vue-tsc 0 错误，九项门禁 PASS；门禁顺带修 `pnpm --dir apps/web exec` 在 pnpm 7 下不注入 `.bin` → 改为在 `apps/web` cwd 执行 `pnpm exec`。

**失效副本自动撤销（2026-11-16，[ADR-016](adr/ADR-016-失效凭据只撤销管家本地副本.md)）**：真机抓取确认 Qoder/Trae/豆包桌面端「退出登录」= 客户端本地清凭据（Qoder 日志仅 `User signed out` + `AuthStore clear`，无远程 logout 请求），WorkBuddy 属腾讯客户端不支持 GUI；网页端远程 signout 会吊销浏览器共享会话。按用户裁决**只清管家副本**：`VaultPort.revoke` 把旧值归档到 `#seq`、删主引用、`vault_items` 保留 `revoked_at/revoked_reason`；`AssessAccountHealth` 在有 NO_AUTH 连败（含由此判出的 `invalid/risk`）或凭据 `expired` 时自动撤销（`risk` 若来自其它信号不触发，幂等，失败只加证据），**连败只算最近一次停靠/轮换（`stored_at`）之后的失败，重新导入的新凭据不被旧失败连坐；全部副本撤销时至少判 `invalid`**；`load` 命中已撤销 → `CredentialRevoked` 仍按 NO_AUTH 处理；`/accounts` 带 `revoked/revoked_at/revoked_reason`，账户详情标「本地副本已撤销，等待重新停靠」。修复重试改为先 `POST /apps/{target}/import` 重新停靠读取客户端新凭据，再 `POST /runs(account_id)`，否则会撞已撤销空引用。**边界**：不调用远程 signout、不删客户端凭据、不强制客户端登出；桌面退出/登录仍由用户手动完成。

**第二批复审修复（2026-11-16）：P1-P4 全修 + 低危四项**。①**网关数据根
split-brain（P1 高）**：`start-server.ps1` 只固化 server 的 `BUTLER_DB`，网关
key/routes/engine 三落点全回落 `%APPDATA%\butler`（正是本机虚拟化层吃 journal
的目录；实测三级 BUTLER_DB 均空、该目录已存在）→ 新 `scripts\start-gateway.ps1`
固化同款 BUTLER_DB + `app.py` 启动一致性告警（未设大声提示 split-brain）+
start-server 的 uv 机器特定硬编码改 `BUTLER_UV`→`~/.local/bin`→PATH 解析链；
②**journal 口径收单源（P2）**：六适配器五处 OFF、第六处（accounts）抄漏
（探针实证 D 盘数据根 DELETE 模式可写非活雷，APPDATA 根才炸）→ 新
`db/conn.py` 连接单源，六处 `_connect` 全部改用，"崩溃可能损坏库本体"修正
口径入注释；③**网关热路径异步化（P3）**：forwarder 的 accounts.get /
pool.acquire / pool.invalidate / meter.record 原全为同步磁盘 I/O 跑在事件
循环上（双进程写同库忙等最坏 5s×候选数卡死全部并发请求）→ 全部
`asyncio.to_thread` 包裹，真上游适配器落地前还清；④**CWD 隐式搬移废除
（P4）**：migrate 候选源砍 CWD 两条（每次构造 engine 都扫 CWD `shutil.move`
搬走同名文件 = 隐式破坏性操作），只留品牌目录两条，测试改钉"CWD 同名文件
不迁移"（净增 2 用例）。低危同批：ledger 幂等判定 SQL 硬编码
CLAIMED/ALREADY → core `ResultKind.is_pass` 谓词（语义单源）、proxy 请求体
20 MiB 上限（413）、vault rotate 中断窗口 docstring 注记、verify 两处
`uv run` 加 `--frozen`（本机旧 uv 重写 uv.lock 两次实证，门禁后不再须手工
还原）。文档收编：A1-03 §7/环境变量表/数据库文件口径、00-项目配置、
guides/01、README。全量 661 passed + 2 skipped，结构门禁 PASS（uv.lock
零污染）、vue-tsc 0 错误。

**浏览器边界收口（2026-11-16，[ADR-014](adr/ADR-014-本地服务浏览器边界与Origin拦截.md)）**：
主控 server 原 `CORSMiddleware(allow_origins=["*"])` + 无鉴权 = **任意网页可驱动本机
签到与网关路由改写**（CORS 只挡读不挡写；localhost 又不受混合内容策略保护，HTTPS
页面可直接打 127.0.0.1）。两道闸落地：①CORS 收显式白名单（Vite 5173 两形态 +
`BUTLER_ALLOWED_ORIGINS` 追加）；②新 `server/security.py` `OriginGuard`（纯 ASGI、
最外层）——带未授权 Origin 一律 403 且不进路由（读/写/预检同拦），**同源放行限定回环**
（Host 与 Origin 同为攻击者域名 = DNS rebinding，挡掉），无 Origin 的 curl/CLI/MCP/
桌面壳直连不受影响。**网关 key 权限口径修正**：NTFS 无 POSIX 权限位，实测
`os.chmod(0o600)` 后 mode 仍 `0o666`（同机其他账户可读）→ `harden_permissions()`
Windows 走 `icacls /inheritance:r /grant:r <user>:F`，真机 icacls 复核继承已撤、
只剩 `ZUOYOU\<user>:(F)`；icacls 不可用/失败 → 告警 + 返回 False，不静默假装安全、
不阻断启动。新测试 20 项（server 15 + gateway 5），全量绿。

**journal_mode=OFF 风险口径修正（2026-11-16）**：原文档写"崩溃丢最后一条写可接受"
是低估计——SQLite 对 `journal_mode=OFF` 的官方表述是**崩溃/掉电可能损坏数据库文件
本身**（回滚日志不存在，页写一半无法回滚），幂等重试只能兜住"重复执行"，兜不住库
损坏。引擎行为**不变**（本机文件虚拟化层仍拦伴生文件，回 WAL 不可行），只把口径
改成如实登记 + **挂账定期备份**（见剩余挂账）。

**豆包双账户纳管落地（2026-11-16）**：多账户底座本已就绪（调度 per-account
checkin.py L62 / 用量 bridge 遍历 / A2-04 account_key），缺口只在豆包切号。
CDP 真机取证（PROTOCOL §9）：客户端菜单无一键切换列表、「添加账号」直通登录页
（手机号/扫码需人工参与）→ **切号不自动化**（ADR-007 决策 7），按用户裁决降级
「只监控不切号」：身份判定（identity.py：`sec_user_id` localStorage + chip 昵称）
→ run/dock/usage 三处身份守卫——**绝不签错账户**；第二账户
`doubao_cn:u66b1e22d`（Leisure520）已登记，活跃 main（逍遥酒鬼）签到照常
ALREADY ✓，B 在 main 会话在场时保守 PENDING（双会话并存语义待下轮取证）。
**环境根治**：本机文件虚拟化层拦截一切 sqlite 伴生文件（-wal/-shm/-journal，
四次 disk I/O error 实证）→ engine 五处 `journal_mode=OFF`（无伴生文件；代价口径
见上一条，**崩溃可能损坏库本体**，备份待落地）+ `BUTLER_DB` 补实现（docstring 承诺未实现的老账）+
**数据根迁至项目内 `data\database\butler.db`**（用户裁决：项目根下建 `data\`，
database/ 放运行库 gitignore、sql/ 放 schema 导出入库版本化，项目数据闭环；
home 目录全被锁 D 盘可写；历史台账已迁移；启动脚本 `scripts\start-server.ps1`
固化 BUTLER_DB；00-项目配置 `{data-root}` 收录）
+ gateway 测试隔离修复（BUTLER_DB→tmp_path）。全量 640 passed。
**schema 生成视图迁 `data/sql/`（2026-11-16）**：`db/` 目录（README+schema.sql）
职能整体迁 `data/sql/`（README 纪律并入，`dump_db_schema.py` OUT 改 `data/sql/butler-schema.sql`
并修 Windows 临时目录清理时序），A4-01 §5 数据根条款同批收编用户裁决（项目内数据根 +
journal_mode=OFF + 原禁止条款适用前提注记），db/ 删除。

**豆包自动切号激活路径实证修正（2026-11-17）**：首版实现「精确匹配昵称行 →
受信任点击」真机 E2E 失败——点击落点正确（hit-test 命中 `[role=menuitem]`
链、pointer-events 全通）但 Radix select 不触发，弹层关闭、无对话框、身份
不变。四路径对照实证（指针三连精确中心 / JS PointerEvent / 键盘 ArrowDown /
JS click）：**键盘导航 + Enter 是唯一可靠激活路径**——ArrowDown 焦点从菜单
容器逐项移动可达所有项，Enter 仅在 `activeElement` 文本精确等于昵称时按下
（添加账号/退出登录零误触，安全性反优于坐标点击）。switch.py 改键盘编排 +
cdp.py 补 `key()` 原语 + 翻转 deadline 20s→45s（翻转含会话重载，实测可超
20s）；测试改焦点状态脚本（16 项全绿，全量 708 passed 三段门禁绿）。

**豆包会话级自动切号落地（2026-11-17）**：用户裁决修订 ADR-007 决策 7 → 决策 8
（双账户注册后头像菜单**存在切换列表**——11-16「无一键切换」只在单账户时期成立；
单会话存活语义用户确认：切号后旧 target 消亡）。switch.py 编排：bringToFront →
点 chip → 精确匹配昵称行 → 信任点击 → 轮询身份翻转（20s 显式超时）→ adapter
复核 → **旧活动页关净**（cdp.py 新原语 Target.closeTarget；残留旧账户 Cookie 的
活动页附着即签错账户，红线前置）。身份登记簿（doubao_identity.json main+others）
作切号定位依据，dock 采集持久化（空采集不覆盖旧簿）；切号留痕进台账 evidence。
**硬边界不变**：登录态过期重登/添加账号仍人工（ADR-015 语义不变，引用已同步）。
**同批两 bug 修复**：①`_ensure_running` 杀净后 settle 6s 再拉起（真机实证：立即
拉起撞单实例锁；「杀→settle→拉起」5s 内 9222 绑定一次成功）②身份守卫 PENDING
修复提示分语境（端口不可达 ≠ 身份不符，不再复用端口语境误导）。门禁三段全绿：
结构 8/8 + 全量 708 passed + vue-tsc 绿（apps/web 内嵌 @butler/sdk 拷贝过期缺
revoked——本机 hoisted 拷贝纪律（见 11-16 沉淀），gen 产物已同步）。新测试 16 项
（switch 编排逐场景 + adapter 接线 + 登记簿 + 两 bug 回归）。

**豆包签到 710010702 平台错误补证（2026-11-17）**：用户反馈「签到失败，请稍后重试」；
真机复现：CDP 页面点击与**客户端自己的「立即签到」XHR** 都返回 `code=710010702 系统错误`。
快照实测该 XHR 为 `version_code=20800&aid=497858&pc_version=2.36.8&doubao_pc_version=5.74.99…`，
body `{"scene":"pc_incentive_task_mvp_v3"}`；JS 可见 URL/请求头未出现 `msToken/a_bogus`（可能在
Cookie 中，已脱敏）。同一时刻 detail 用同一会话仍 `code=0`、`checked_in_today=false`。**结论：
702 不是本连接器 detail 参数缺项/页面通道回归，而是账号/会话/平台侧错误**；已停止连续点击，
保留自动班次重试。PROTOCOL §2 已更新现场证据与「702 停止连点」处置。

**请求快照（2026-11-17）**：新增 `doubao_cn/snapshot.py`，每次 detail（含复查）落脱敏 JSONL，
点击前安装页面 fetch/XHR 只读旁路，抓客户端自己的 `/alice/ug/campaign/...` checkin 请求
（URL/query/headers/body/response）。位置 `~/.butler/doubao_requests/doubao_requests-YYYY-MM-DD.jsonl`
（`DOUBAO_REQUEST_DIR` 可覆盖；`DOUBAO_REQUEST_CAPTURE=0` 关闭）。Cookie/Authorization/
`msToken`/`a_bogus`/`web_id`/`tea_uuid` 只存 hash，不落明文；快照失败不阻断签到。本次 `main`
失败样本已落盘；`Leisure520` 2026-11-17 08:46 +200 为台账成功记录，当时未开捕获，下一次成功
会自动生成成功样本供对照。`test_doubao_snapshot.py` 3 项通过。

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

- **`journal_mode=OFF` 的定期备份未落地**（2026-11-16）：OFF 无回滚日志 → 崩溃/掉电
  可能损坏库本体（口径已修正，不再是"丢最后一条写"）。在伴生文件被拦的环境里换不回
  WAL，唯一兜底 = 定期 `sqlite3.Connection.backup()` 快照（建议每小时/每次写批次后
  落 `data/database/backups/`，保留 N 代）；实现前**风险敞口在**，数据损坏不可恢复。

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
