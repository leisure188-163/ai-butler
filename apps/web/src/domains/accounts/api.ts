/**
 * 账户域端点（对应 server routes/accounts.py）：账户册、别名、删除、会话扫描。
 *
 * 容错语义随函数走：除特别注明外，非 2xx 抛 ApiError，网络异常原样传播（红线 5）。
 */
import { apiBase, post, request } from "@/shared/api/http";
import type {
  AccountDeleted,
  AccountItem,
  SessionsScan,
} from "@/domains/accounts/types";

export function getAccounts(): Promise<AccountItem[]> {
  return request<AccountItem[]>(`${apiBase}/accounts`);
}

/** 改账户别名（ADR-030）：空串 = 清除，显示回落到连接器给的名称。
 * account_id 含冒号（platform:code），必须 encode 后再进路径。 */
export function setAccountAlias(accountId: string, alias: string): Promise<AccountItem> {
  return request<AccountItem>(`${apiBase}/accounts/${encodeURIComponent(accountId)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ alias }),
  });
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
