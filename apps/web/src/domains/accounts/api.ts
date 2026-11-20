/**
 * 账户域端点（对应 server routes/accounts.py）：账户册、创建/编辑、凭据槽位、删除、会话扫描。
 *
 * 容错语义随函数走：除特别注明外，非 2xx 抛 ApiError，网络异常原样传播（红线 5）。
 */
import { apiBase, post, request } from "@/shared/api/http";
import type {
  AccountDeleted,
  AccountItem,
  CredentialItem,
  SessionsScan,
} from "@/domains/accounts/types";

export function getAccounts(): Promise<AccountItem[]> {
  return request<AccountItem[]>(`${apiBase}/accounts`);
}

/** 账户真实身份（ADR-033）：只显示/匹配，不参与编址。 */
export type AccountIdentityPayload = {
  nickname?: string;
  email?: string;
  uid?: string;
  org?: string;
  source_key?: string;
};

/** 手建账户：account_code 是可空人工后缀，不自动生成；首份凭据可同请求写入。 */
export type AccountCreatePayload = {
  platform_code: string;
  account_code?: string;
  account_name: string;
  alias?: string;
  base_url?: string;
  identity?: AccountIdentityPayload;
  kind?: string;
  secret?: string;
  slot?: string;
  label?: string;
  expires_at?: string | null;
};

/** 账户编辑：显示/运营字段 + 人工后缀；account_id 永不改。 */
export type AccountPatch = {
  alias?: string;
  account_name?: string;
  account_code?: string;
  active?: boolean;
  base_url?: string;
  identity?: AccountIdentityPayload;
};

export function createAccount(payload: AccountCreatePayload): Promise<AccountItem> {
  return request<AccountItem>(`${apiBase}/accounts`, post(payload));
}

export function patchAccount(accountId: string, patch: AccountPatch): Promise<AccountItem> {
  return request<AccountItem>(`${apiBase}/accounts/${encodeURIComponent(accountId)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  });
}

/** 改账户别名（ADR-030）：空串 = 清除，显示回落到 core 计算的 account_label。
 * account_id 含冒号（platform:code），必须 encode 后再进路径。 */
export function setAccountAlias(accountId: string, alias: string): Promise<AccountItem> {
  return patchAccount(accountId, { alias });
}

/** 追加凭据槽位（ADR-033）：同账户同 kind 多份 key 用 slot 区分。 */
export function addAccountCredential(
  accountId: string,
  payload: { kind: string; secret: string; slot?: string; label?: string; expires_at?: string | null },
): Promise<CredentialItem> {
  return request<CredentialItem>(
    `${apiBase}/accounts/${encodeURIComponent(accountId)}/credentials`,
    post(payload),
  );
}

/** 撤销单个槽位：归档旧值、清主引用；客户端会话不受影响。 */
export function revokeAccountCredential(
  accountId: string,
  kind: string,
  slot: string,
): Promise<{ account_id: string; kind: string; slot: string; revoked: boolean }> {
  return request(
    `${apiBase}/accounts/${encodeURIComponent(accountId)}/credentials/${encodeURIComponent(kind)}/${encodeURIComponent(slot)}`,
    { method: "DELETE" },
  );
}

/** 删除账户（2026-11-19）：账户行 + 关联凭据一并删除，不留脏数据。 */
export function deleteAccount(accountId: string): Promise<AccountDeleted> {
  return request<AccountDeleted>(`${apiBase}/accounts/${encodeURIComponent(accountId)}`, {
    method: "DELETE",
  });
}

/** 扫一次本机会话并入库（只读枚举 + 幂等）；503 = 部署未装配扫描源，detail 直显 */
export function scanAccountSessions(accountId: string): Promise<SessionsScan> {
  return request<SessionsScan>(
    `${apiBase}/accounts/${encodeURIComponent(accountId)}/sessions/scan`,
    post(),
  );
}
