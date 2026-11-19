/**
 * 前端 DTO —— 派生自 packages/sdk 契约（A1-02 §2 契约先行，2026-11-12 起）。
 *
 * 纪律（红线 2/4）：字段名与可空性一律来自 server Out 模型的生成类型
 * （@butler/sdk → schema.d.ts），**禁止手写字段形状**——server 改字段，
 * vue-tsc 当场报错（门禁第 8 项收编了 vue-tsc）。
 * 唯一允许的本地加工 = signal 窄化：契约里是 string（core 出产字面量直传），
 * UI 谓词只消费五分类 Signal（端零映射：页面不认识 Status/HealthLevel 本身）。
 */
import type { components } from "@butler/sdk";

type Contract = components["schemas"];

export type Signal = "ok" | "notice" | "attention" | "danger" | "quiet";

export type PageName =
  | "签到概览"
  | "平台管理"
  | "账户管理"
  | "用量管理"
  | "运行日志"
  | "系统设置";

/** signal 窄化包装：除 signal 外的形状全部继承契约 */
type WithSignal<T> = Omit<T, "signal"> & { signal: Signal };

export type CredentialItem = WithSignal<Contract["CredentialOut"]>;
/** 嵌套字段同样要窄化：credentials 里的凭据行也是 UI 消费面（signal 必须是 Signal） */
export type AccountItem = Omit<Contract["AccountOut"], "signal" | "credentials"> & {
  signal: Signal;
  credentials: CredentialItem[];
};
export type PlatformItem = Contract["PlatformOut"];
export type ImportResult = Contract["ImportOut"];
/** 平台编辑载荷（UI 只提交三项契约字段；端不做业务判定） */
export type PlatformPatch = {
  platform_name?: string | null;
  active?: boolean;
  times?: string[] | null;
};
/** 行操作项（2026-11-18）：操作列直连 ≤2 个，其余进「更多」下拉 */
export type RowAction = {
  key: string;
  label: string;
  /** 悬停说明（2026-11-19）：动作名不足以表达语义时补一句，如「重新接入」 */
  title?: string;
  /** 图标化动作（2026-11-19）：有值时渲染图标按钮，label 只作 aria-label/title 用 */
  icon?: "edit" | "refresh" | "dots";
  danger?: boolean;
  disabled?: boolean;
};
/** 自定义平台（2026-11-18）：草稿 = 用户填的表单形状；目录行 = 已登记的自定义平台 */
export type CustomPlatformDraft = Contract["CustomPlatformIn"];
export type CustomPlatformRow = Contract["CustomPlatformOut"];
export type CustomPlatformSaved = Contract["CustomPlatformSaved"];
export type CustomPlatformDeleted = Contract["CustomPlatformDeleted"];
export type EvidenceItem = Contract["EvidenceOut"];
export type RunItem = WithSignal<Contract["RunOut"]>;

/** 流量数据（R2-E）：同样全部契约派生；quota_low 是 core 谓词出产的包名列表，UI 只做布尔渲染 */
export type PackageRow = Contract["PackageQuotaOut"];
export type ForecastRow = Contract["ForecastOut"];
export type LedgerRow = Contract["LedgerEntryOut"];
export type RadarRow = Contract["RadarAccountOut"];
export type CollectOutcome = Contract["CollectOutcomeOut"];

/** 网关路由管理面（R4-G6）：契约派生；校验单源在 core（UI 不复写规则，422 detail 直显） */
export type GatewayRouteRule = Contract["RouteRuleOut"];
export type GatewayRoutes = Contract["GatewayRoutesOut"];

/** 会话清单（R5-S1）：kind/level = core 词表原样，UI 只渲染不判类 */
export type SessionItem = Contract["SessionOut"];
export type SessionsScan = Contract["SessionsScanOut"];

export type ThemeName = "system" | "qinglan" | "paper" | "dark" | "mist";

export interface Settings {
  autoRefresh: boolean;
  intervalSec: number;
  theme: ThemeName;
}

/** 平台检索条件（2026-11-18）：纯前端筛选，不是契约字段 —— 端不做业务判定 */
export type PlatformQuery = {
  keyword: string;
  status: "all" | "active" | "inactive";
  kind: "all" | "web" | "client";
  sort: "code" | "name" | "accounts";
};
