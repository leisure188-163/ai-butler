---
name: butler-adr-006
description: qoder 走声明式扩展接入——列表领取形状进 schema、凭据与机器身份做成 kind，不写 per-app 代码。TRIGGER when 实现 qoder/评估声明式 schema 扩展时
version: "1.0.0"
level: must
---

# ADR-006 · qoder 接入形状 = 声明式扩展，不是 Python 适配器

- **状态**：Accepted
- **日期**：2026-11-11
- **决策者**：架构会话（与用户裁决 kind 收敛原则同日）
- **关联**：A2-02 §3（kind 收敛原则）、§4（声明式 schema）、ADR-004/003、qoder PROTOCOL.md

## 背景

qoder 协议（NOTE-02 取证，2026-10-21）：campaigns 活动列表 → 逐项 claim
（幂等），判定靠**结构化字段**（claimStatus 枚举）而非数字业务码；凭据是
DPAPI + AES-256-GCM 双层文件（auth.v1.dat）；活动接口强制 8 个机器身份头
（由客户端自带 runtime-info 组件产出，缺头 = 服务端静默返回空活动列表）。

与 trae（单接口、数字码、SS_AES）形状不同。候选：
A. Python 适配器（A2-02 三级之二）——最快但 per-app 平行代码，违背 kind 收敛
   原则；且"列表领取"形状 workbuddy 成长中心大概率同构，写了就重复
B. 声明式 schema 扩展——把列表领取做成受限声明形状，凭据/机器身份做成 kind

## 决策

**方案 B**：qoder 以声明式 YAML 接入，扩展全部发生在引擎层（所有连接器共享）：

1. **声明式 schema 增补"列表领取"受限形状**（A2-02 §4 演进，`extra=forbid`
   依旧）：
   - `status` 增 `list_path`（数组所在点路径）+ `item_filter`（等值筛选字典）
     ——谓词 = "筛选后存在待领项"；全空 = ALREADY 语义
   - `claim.url` 支持引用 status 响应列表项字段（如 `{campaign.id}`），
     引擎对筛选结果**逐项**领取，全部幂等
   - 不做任意编排（不是 YAML 图灵机）：超出"列表→逐项领取"形状 → 端口实现
2. **凭据 kind 扩展**（engine vault/dock 层，一次实现共享）：
   - `auth.kind` 新增 DPAPI+AES-GCM 双层文件的解锁处理器（命名按解锁协议，
     不按应用名）
   - dock 扫描器新增对应扫描器：读 `auth.v1.dat` + `Local State` 解密出
     token/expiresAt 入 vault
3. **机器身份头组 kind**：dock 时定位客户端自带 runtime-info 组件
   （安装根定位顺序见 PROTOCOL），运行产出机器身份头组存 vault（kind 按
   "官方组件机器身份"语义）；运行时 8 个头全部走 `dynamic_headers` 模板
   逐头引用——头名在声明里显式列全，不在代码里
4. **静默陷阱显式化**（红线 5，对旧行为的改良）：旧系统"缺 Cosy-ClientType
   返回空列表""缺机器身份不返回日常活动"都是静默降级——新系统：dock 找不到
   组件 = 显式 issue；运行时缺头/缺凭据 = 显式 FAILED + repair_hint（重新
   导入），绝不退回"普通请求"

## 排除项

- doubao（CDP 编排）不适用本决策——超声明表达能力，走端口实现（届时裁决其
  dock 形态）
- 反代/网关形态（M3）不适用

## 后果

**正面**：

- qoder 接入 = 两个 YAML + 三个 kind 处理器（引擎层，通用件）——零 per-app 代码
- "列表领取"形状 + DPAPI 双层凭据 + 官方组件机器身份，workbuddy/其他阿里系
  客户端大概率复用（取证后如确认即白得）
- 声明式表达能力边界被清晰化（列表领取在内，任意编排在外）

**负面/约束**：

- schema 复杂度上升：`list_path/item_filter/each` 三个新声明字段要有测试
  覆盖（含筛选为空/多项/claim 部分失败的语义）
- runtime-info 是外部进程依赖（安装目录变动/组件升级会破坏定位）——dock
  issue 必须把候选路径与排查动作写清楚
- qoder 的 claim 响应形状（replayed 字段等）待真机取证补 PROTOCOL——实现
  前置条件
