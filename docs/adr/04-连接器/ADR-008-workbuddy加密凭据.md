---
name: butler-adr-008
description: workbuddy 接入形状 = 端口实现 + 加密凭据解密链（native_helper 通用原语 + helper.js 契约搬运，2026-11-18 扩展 expect=field 解任意信封字段）；范围收敛为签到最小集（修订 A0-01/A2-02"全链路"字面）；凭据现用现取零 vault；dock = 体检 + 本地只读身份解密（按 ADR-003 扩展）。TRIGGER when 实现 workbuddy/评估加密凭据类连接器/裁决连接器首期范围时
version: "1.1.0"
level: must
---

# ADR-008 · workbuddy 接入形状 = 加密凭据解密链端口实现，范围收敛为签到最小集，dock = 体检 + 身份解密

- **状态**：Accepted（v1.1 修订见决策 2/4 的 2026-11-18 注记）
- **日期**：2026-11-11（v1.1：2026-11-18）
- **决策者**：架构会话（用户两项裁决：首期 = 签到最小集 / dock = 纯体检 + 指引）
- **关联**：A2-02 §3（端口实现合法形态）、§7（实现顺序——本 ADR 修订其
  "workbuddy_cn（成长中心全链路）"字面）、ADR-004（方言注册表）、ADR-007
  （dock 体检先例 / 零 vault 先例 / 通用原语先例）、workbuddy_cn PROTOCOL.md、
  旧仓库 NOTE-01-workbuddy域接口取证.md

## 背景

workbuddy 是第四家接入的连接器，与前三家形状又不同：会话凭据是桌面端登录后自动
写出的 JSON 文件，**本机实况为新版 `$wbEncrypted` 加密信封**（suite=1，
AES-256-GCM + keyId 校验，2026-11-11 核实）——明文直读不可行，解密必须借
客户端自带 Electron 运行时的内部绑定（`atRestSecretKey`）。旧仓库以
「JS 原样注入 + 隐藏子进程」实现并稳定运行（NOTE-01 §4）。

同时 A0-01 §4 / A2-02 §7 字面写「4. workbuddy_cn（成长中心全链路）」，但
接入顺序语义是「由简到繁验证底座」，前三个连接器实际都只做了签到单动作；
成长中心 = 7 步 17 端点 + 旅行状态机 / 任务五态 / 补登候选日算法等易错契约
（旧域约 2500 行的大头），一次到位的验收风险高。

## 决策

1. **范围收敛 = 签到最小集**（2 端点单动作，与前三家同型）。第四连接器的
   验证价值在**凭据解密链**——第三种凭据形态（trae 声明式文件直读 / doubao
   CDP Cookie 现取 / workbuddy 加密信封子进程解密），不在单连接器端点数量。
   成长中心 7 步 = 后续**独立批次**（紧随首批接入立项，按 NOTE-01 §6 顺序
   纪律另裁）。本条修订 A0-01 §4 / A2-02 §7 的"全链路"字面：由简到繁的
   "繁"落在凭据链复杂度，不落在单连接器端点数。
2. **接入形态 = core 端口实现**（A2-02 §3 唯一合法 per-app 形态）：
   `WorkbuddyProvisionPort` 只实现 `capabilities()` + `run()`。解密子进程
   机制下沉为 connectors 包通用原语 `native_helper.py`（JSON-stdin 管道 +
   硬超时 + reason 白名单 + 子进程环境剥离，与 cdp.py 同型的可注入端口）；
   `workbuddy_cn/helper.js` 自旧仓库 helper_js.py **原样搬运禁改**——
   JS/编排形状是协议契约不是代码搬运（与 trae SS_AES 常量、doubao 点击
   编排同性质），AES-GCM 细节在客户端 binding 里，重写即偏离实测契约。
   **修订（2026-11-18，ADR-003 扩展）**：helper.js 增加可选
   `expect:"field"` 分支——跳过明文 token 字符集校验，用于解任意信封字段
   （account.nickname）；缺省路径（无 expect）行为与旧契约逐字节一致，
   reply 形状 `{version,ok,accessToken}` 不变。Python 侧新增通用
   `decrypt_field`（session.py），`decrypt_envelope` 保持 token 契约。
3. **凭据语义 = 现用现取，零 vault 申报**（doubao Cookie 现取同型）：每次
   run 定位文件 → 解析 → 必要时子进程解密 → 内存构造请求头 → 用完即弃。
   理由：客户端 30 天自动刷新 token 并重写凭据文件，任何入库持久化必然
   脱节过期；旧系统铁律"token 只进内存不落盘"；不碰 refreshToken、不与
   客户端争抢轮换。manifest 无 credential 段。
4. **dock = 纯体检 + 指引，不自动拉起**（用户裁决）：凭据文件存在？JSON +
   必备字段？token 形态可识别？runtime 可定位（仅信封形态是硬伤）？——
   四项只读，零网络零解密（对齐旧仓库 doctor"不解密不联网"纪律）。
   不拉起客户端：解密用 `ELECTRON_RUN_AS_NODE` 离屏执行，**不需要客户端
   运行中**；登录是扫码/手机号交互行为，拉起也完不成闭环。缺凭据 →
   导入指引「打开 WorkBuddy 客户端登录」。
   **修订（2026-11-18 增补，2026-11-20 按 ADR-003 更正）**：体检四项之后追加一项
   **本地只读身份解密**——解 `account.nickname` 信封得昵称并写入 `account_name`；
   `account_code` 留空等用户人工关联。仍零网络零写零拉起，昵称解密失败不阻塞
   dock（如实记 note）。真机 mac 实测端到端通
   （2026-11-18，import → 显示名「大海」，claim ALREADY）。
5. **结果语义**：401→EXPIRED / 403→NO_AUTH（**不判登录过期**，旧仓库
   auth_failure_dto 原语义）/ 活动未开启（active=false）→PENDING /
   TransportError 与 5xx→FAILED+evidence。与 ADR-007 的"CDP 不可达 =
   PENDING"区分：那是"客户端没跑"且 dock 能自愈的本机暂态；HTTP 传输层
   故障按 transport.py 契约如实 FAIL，由调度高密度触发兜底（旧仓库
   NETWORK/TIMEOUT 同语义，验收表注明映射）。方言 = `{"10001": ALREADY}`
   （claim 400 已签码）；claim 其他未知码刻意不注册 → UnknownEngineCode →
   用例层 FAILED + PROTOCOL_CHANGED 事件（红线 5）。
6. **多版本并存为常态**：本机 WorkBuddy AI 5.9.4（HKCU）+ 5.9.3（HKLM）
   并列——候选 runtime 按顺序尝试解密，KEY_MISMATCH 换下一个，全败 →
   NO_AUTH + hint「用 `WORKBUDDY_EXE` 指定与凭据匹配的客户端」。
   exe 从注册表 `DisplayIcon` 取（剥引号 + 剥 `,0` 图标索引后即主 exe
   本体；`InstallLocation` 实测为空）；条目匹配 = **DisplayName
   `WorkBuddy` 前缀**（大小写不敏感，兼容 "WorkBuddy AI" 变体——旧仓库
   正则 `WorkBuddy(\s+\d+…)?` 匹配不上 AI 变体，勿沿用）。环境变量沿用
   旧仓库名（`WORKBUDDY_EXE` / `WORKBUDDY_AUTH_FILE`），与 doubao 纯名
   惯例一致。

## 排除项

- 成长中心 7 步（旅行 / 任务 / 补登 / 兑换 / 双盲盒 / 展示值）——后续批次
  （决策 1），PROTOCOL §2.1 留端点速查
- taskbot 进度制造器——耗真实对话额度，不做
- 活跃保底对话（chat 补一次对话防断签）——耗真实额度且"对话"不是"领取"
  动作语义；活跃日历只读查询可随成长中心批次评估
- 自动拉起客户端（见决策 4）

## 后果

**正面**：

- 底座验证完备收官：四种接入形状（声明式 / 声明式+风控头 / CDP 界面通道 /
  加密凭据端口实现）+ 三种凭据语义（vault 申报 / 零凭据现取 / 加密解密
  现取）全部落过，"不加特殊分支接入新模型"硬标准在最复杂凭据链上收口
- `native_helper.py` 与 `cdp.py` 同型——未来任何"客户端加密凭据"类连接器
  复用同一套原语，kind 收敛原则保持
- 现用现取 = 零过期轮换问题、零凭据落盘、攻击面最小

**负面/约束**：

- 解密链依赖客户端内部绑定（`electron_browser_workbuddy_storage`）——客户端
  大版本改版可能失效；症状与重取证方法记 PROTOCOL §4 / NOTE-01 §13
- 每次运行跑一次子进程解密（≤10s）——预算 120s 内绰绰有余
- 成长中心权益（旅行礼物 / 任务奖 / 盲盒）首期不自动领取——批次立项前
  用户需手动领取或沿用旧仓库脚本
