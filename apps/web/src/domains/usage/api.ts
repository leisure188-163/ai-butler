/**
 * 用量域端点（对应 server routes/usage.py）：雷达与采集。
 */
import { apiBase, post, request } from "@/shared/api/http";
import type { CollectOutcome, RadarRow } from "@/domains/usage/types";

/** 独立容错（语义随函数走）：失败静默为 []（矩阵额度列显示「—」），不拖垮主数据 */
export async function getRadar(): Promise<RadarRow[]> {
  try {
    return await request<RadarRow[]>(`${apiBase}/usage/radar`);
  } catch {
    return [];
  }
}

export function collectUsage(): Promise<CollectOutcome[]> {
  return request<CollectOutcome[]>(`${apiBase}/usage/collect`, post());
}
