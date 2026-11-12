# Kabao 钱包视觉语言 · 设计文档

- 日期：2026-11-12
- 状态：已获用户批准（方向锚点 + 桌面适配 A 案），待用户终审本文档
- 范围：apps/web 纯视觉层 + 卡包页布局重构；不动 IA/路由/API/后端
- 可视化依据：.superpowers/brainstorm/87716-1794495756/content/（ai-tells / directions / tencent-wallet.html）

## 1. 背景与动机

用户对 D2 v4「卡纸与墨」实现仍觉"太 AI 化"。经浏览器小样多选确认，痛点为三项
（终端答案 ABD 为准；字体项未确认为痛点，本轮不动）：

- **A 通用面板骨架**：圆角 panel + 浅边框 + 微阴影悬浮灰底，等距网格；
- **B 状态灯到处都是**：彩色圆点灯 + 胶囊徽章铺满界面，仪表盘腔调；
- **D 均匀节奏无层级**：信息同等视觉重量，眼睛没有落点。

用户随后给出方向锚点：**腾讯卡包模式**（微信卡包 / iOS Wallet 一类）——
卡是唯一主角。该模式天然消解三个痛点：卡堆取代面板、墨印取代状态灯、
卡的自然堆叠产生节奏。

桌面适配两案（A 钱包架两栏 / B 单列卡包）经小样比对，用户选定 **A 钱包架**。

## 2. 目标与非目标

**目标**

1. 建立钱包隐喻的统一视觉语言：卡是主角，账本行是数据的默认形态，墨印是状态的唯一表达。
2. 卡包页重构为钱包架（左卡堆 + 右详情），落实层叠、空卡槽、详情栏交互。
3. 其余页面（首页/雷达/记录/提醒/设置/侧栏）轻改对齐同一语言。
4. 全部新样式走 tokens.css 变量，三主题（paper/dark/warm）与 reduced-motion 纪律保持。

**非目标**

- 不改信息架构（A3-01 六页 + 侧栏 + hash 路由全部保留）。
- 不改后端契约与 API；types.ts 不新增任何手写字段。
- 不动字体栈（D4 系统字体保留）；不引入外部字体或图标库。
- 不加复杂动效；首页卡扇揭示仍是唯一 orchestrated moment。

## 3. 设计语言总纲

| 痛点 | 旧 | 新 |
| --- | --- | --- |
| A 面板骨架 | `.panel` 圆角浮板铺满各页 | 卡堆 + 账本行（细线分节）；`.panel` 收窄为设置件专用 |
| B 状态灯 | `.lamp` 圆点灯 + 胶囊徽章 | **墨印方章**（`.stamp` 体系转正为唯一状态表达）；`.lamp` 全系删除 |
| D 均匀节奏 | 等距网格 | 钱包架两栏非对称；字号与留白分层（页题 > 节签 > 行文 > 证据） |

不变的基底：D2 卡纸与墨色板与三主题、卡面 6 色（`--card-face-*`）与 `faceOf` 哈希、
signal 五分类色相纪律、动效 token（`--motion-*`、reduced-motion 归零）。

**墨印（stamp）语义**：色相只由 core signal 分类决定（ok/notice/attention/danger/quiet
→ `--color-*-ink`），纸面上用 `--color-*-ink` 档；卡面深底上用提亮档（沿用 BizCard
现有亮色系）。形态统一为 1.5px 描边方章、字距 0.12em、9–10px。

**空态纪律**（ux 检索命中）：空态必须给消息 + 动作，不留白屏——空卡槽即导入动作本身。

## 4. 卡包页 = 钱包架（重构核心）

### 4.1 布局

- 两栏：左卡堆列约 62%，右详情栏约 38%，中间 1px 细线分隔（`--color-border`），
  两栏均为纸底（不浮动、无阴影面板）。
- 页头：页题「卡包」+ 账本式概览（`N 应用 · M 卡 · K 待修`）+「一键导入/一键领取」
  （一键导入为主按钮，一键领取按现有可用性禁用逻辑）。
- `actionMsg`（导入/领取结果转述）沿用现有 `.action-msg` 件，置于页头下。
- **≤900px 断点**：详情栏下沉为选中卡下方就地展开（accordion 形态），两栏转单列。

### 4.2 卡（BizCard 重构）

真实卡面解剖，自上而下：

1. 左上：应用名首字**圆章**（face 色提亮底、墨字或白字按 face 对比度）+ 应用名 + 等级徽
   （1px 描边小签，`AccountOut.level` 契约字段）；
2. 中部：卡号 = `account_id`，mono、0.06em 字距、超长省略（现状保留）；
3. 底部：有效期（`earliestExpiry`）+ 右下角**墨印角章**（signal）。

变更：删除顶部 5px 状态色条（`bizcard::before`）与卡面圆灯（`.bc-lamp`）；
`--card-face-*` 升级为渐变对 token（`--card-face-{n}-hi/-lo`，6 组），卡面用
135deg 线性渐变。`aspect-ratio 1.586`、圆角、chip 金章保留。

交互：hover 抬起幅度收敛（translateY(-3px)）；selected 用 outline 现状保留；
`--i` 揭示动画与 reduced-motion 行为不变。

### 4.3 卡堆（M1 单账户）

- 契约现状为 M1 单账户：`AppOut.account_id` 是「{id}:main 卡位」（一应用至多一卡，
  server/routes/api.py:55 注释为证），因此**不做按应用分组层叠**——那是没有数据支撑的死特性。
- 卡堆 = 纵向紧凑卡列（卡间距 12px、卡宽约 340px），排列顺序 = accounts 现有顺序；
  钱包感由卡面真实感与空卡槽承担。多账号层叠留待 M2 多账户落地时另案引入。

### 4.4 空卡槽（CardSlot）

- 未导入应用（`app.account_id === null`）= 虚线槽（1.5px dashed `--slot-dash`，透明底），
  槽内文案「＋ 导入 {app.display}」，点击即发起导入（复用现有 emit 链）。
- 槽与卡同形（aspect-ratio 1.586、同宽），排列在卡堆末尾。
- 已导入（`account_id` 非空）必有卡，不设槽；「未泊位」语义在 M1 下不存在。

### 4.5 详情栏（新组件 CardDetail.vue）

- 顶部小签「详情 · {应用 display}」；大卡（复用 BizCard，selected 态）；
- 凭据账本行：每行 `kind`（加粗）· `level` · 有效期 · 行尾墨印（credential signal），
  行间 1px 细线；无凭据显示安静行；
- 证据（`evidence` 原文直渲染，不加工）+ 修复建议（`repair_hint`，`row-fix` 色）；
- 动作区：「领取」主按钮（复用现有 `claim` emit 链与 `busyTarget` 禁用逻辑）。
- 交互：点卡 = 选中（`selectedId` 现有 toggle 逻辑复用）；再点同卡取消选中，
  详情栏显示安静占位「点一张卡看它的内里」。

## 5. 其余页面（同一语言轻改）

- **首页**：卡扇（fan）与揭示动画保留，卡换新面；待处理列表去 `.panel` 包裹，
  改账本行（细线分节）；行首灯删除，结论改行尾墨印。
- **雷达**：账号节头改为 face 色窄横幅（应用名 + 账号 mono）；包体保留大数字 +
  进度条（墨色填充不动）；`.panel`/`.pkg` 边框改细线分节；「低额」stamp 不动。
- **记录**：表格保留（账本本质）；外壳 `.panel` 改细线框 + 纸底；`.stamp` 原样。
- **提醒**：三个分节的行首灯全删；行尾墨印表达结论（即将到期=notice 印，
  需要留意=对应 signal 印）；「去卡包」ghost 按钮不动。
- **设置**：`.field` 件与分节保留；`.panel` 改细线框（视觉降权，结构不动）。
- **侧栏**：结构、active 金条、徽标不动；仅随 token 微调（无逻辑变更）。

## 6. Token 与组件变更清单

**tokens.css**

- 新增：`--card-face-{1..6}-hi/-lo`（渐变对，三主题各配）、`--slot-dash`。
- 不动：signal 五色及 `-ink`/`-weak` 档、字体栈、间距/圆角/动效 token、主题切换机制。

**ui.css**

- 删除：`.lamp` 全系（含 `.lamp--mini`）。
- 收窄：`.panel` 注释改为设置件/表件专用；账本行基准件（`.rows/.row`）保留并
  补一条「行尾墨印」示例注释。

**组件**

- `BizCard.vue`：按 §4.2 重构（删色条删灯、加圆章/等级徽/墨印角章、渐变卡面）。
- 新增 `CardDetail.vue`：详情栏（§4.5）；props 为选中账号 + 关联应用 + busy 态。
- `WalletPage.vue`：布局改钱包架两栏；空卡槽为本页局部标记；
  `selectedId` 逻辑保留；apps 区的行列表由空卡槽取代。
- 其余页面：仅模板/样式级改动，script 逻辑除删除 lamp 相关绑定外不动。

## 7. 红线映射

- 红线 2（端零映射）：墨印色相只消费 signal 五分类；status 原文仅在记录页如实展示；
  证据/repair_hint 为 core 产文案，直渲染不加工。
- 红线 4（契约先行）：`level`、`signal`、`evidence` 等全部来自既有 `@kabao/sdk` 派生
  类型（types.ts），零手写字段。
- 红线 5（显式报错）：`loadError`/`actionMsg` 行为不变。
- 红线 6（token 唯一来源）：新样式全部走 tokens.css 变量；不出现裸 hex
  （BizCard 卡面提亮档如需新增，进 token，不入组件）。
- 红线 7（门禁）：提交前 `python3 scripts/verify_project.py --project . --test` 全绿
  （含 vue-tsc）。

## 8. 验收

1. 门禁八项全绿。
2. 真机 dev server 交互验证：卡选中/取消、空卡槽导入、详情栏领取、
   一键批量、actionMsg 转述；browser-use 用 take_snapshot + evaluate_script 组合
   （已知截图不可靠）。
3. 三主题（paper/dark/warm）+ ≤900px 断点逐页过一遍；卡片文案在 dark 主题对比度
   达标（墨印 ≥4.5:1）。
4. 对照 ui-ux-pro-max pro-rules 交付清单（焦点可见、reduced-motion、语义色 token、
   触达目标、空态动作）。

## 9. 开放问题

- 字体气质（痛点 C）：本轮未确认为痛点、不处理；若后续要动，另开一轮（涉及 D4 裁决）。
- 卡面提亮档具体色值在实现期以对比度实测为准（dark 主题重点核对 face-4/face-5）。
