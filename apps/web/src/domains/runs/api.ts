/**
 * 运行域端点（对应 server routes/runs.py）：台账、待办、发起领取、一键领取。
 */
import { apiBase, post, request } from "@/shared/api/http";
import type { RunItem } from "@/domains/runs/types";

export function getRuns(): Promise<RunItem[]> {
  return request<RunItem[]>(`${apiBase}/runs?limit=200`);
}

export function getPending(): Promise<RunItem[]> {
  return request<RunItem[]>(`${apiBase}/pending?limit=20`);
}

export function createRun(body: {
  target: string;
  kind?: string;
  account_id?: string;
}): Promise<RunItem> {
  return request<RunItem>(`${apiBase}/runs`, post(body));
}

export function claimAllRuns(): Promise<RunItem[]> {
  return request<RunItem[]>(`${apiBase}/runs/claim-all`, post());
}
