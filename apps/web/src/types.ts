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

export type PageName = "仪表盘" | "平台" | "账户" | "流量" | "日志" | "设置";

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

export type ThemeName = "system" | "paper" | "dark" | "warm";

export interface Settings {
  autoRefresh: boolean;
  intervalSec: number;
  theme: ThemeName;
}
