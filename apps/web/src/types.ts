export type Signal = "ok" | "notice" | "attention" | "danger" | "quiet";

export type PageName = "首页" | "卡包" | "记录" | "提醒" | "设置";

export interface CredentialItem {
  account_id: string;
  kind: string;
  level: string;
  signal: Signal;
  expires_at: string | null;
}

export interface AccountItem {
  account_id: string;
  level: string;
  signal: Signal;
  evidence: string[];
  repair_hint: string | null;
  credentials: CredentialItem[];
}

export interface EvidenceItem {
  summary: string;
  raw_code: string | null;
}

export interface RunItem {
  id: string;
  kind: string;
  target: string;
  account_id: string;
  started_at: string;
  finished_at: string | null;
  status: string | null;
  signal: Signal;
  evidence: EvidenceItem[];
  repair_reason: string | null;
  repair_action_id: string | null;
}

export interface AppItem {
  id: string;
  display: string;
  capabilities: string[];
  credential_kinds: string[];
  schedule_times: string[];
  account_id: string | null;
}

export interface Settings {
  autoRefresh: boolean;
  intervalSec: number;
}
