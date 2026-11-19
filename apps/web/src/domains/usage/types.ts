/**
 * 用量域 DTO（对应 server routes/usage.py 的 Out 模型）。
 *
 * quota_low 是 core 谓词出产的包名列表，UI 只做布尔渲染（端零映射）。
 */
import type { contract } from "@/shared/types/contract";

export type PackageRow = contract["PackageQuotaOut"];
export type ForecastRow = contract["ForecastOut"];
export type LedgerRow = contract["LedgerEntryOut"];
export type RadarRow = contract["RadarAccountOut"];
export type CollectOutcome = contract["CollectOutcomeOut"];
