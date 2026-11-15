/**
 * 端点访问单源（conventions/4 §2.4，业务子域分包 2026-11-14）：
 * URL 与响应形状只写此处——加端点先来这里，与 server routes/ 四域模块同构。
 *
 * 纪律：
 * - 类型派生自 ./types（其派生自 @butler/sdk 契约，红线 4 单源不变）
 * - 容错语义随域函数走：getRadar / getOpenApiInfo 永不 throw（失败静默，
 *   语义注释随函数）；其余端点非 2xx 抛 ApiError（detail/status 透传，
 *   文案由调用方拼装），网络异常原样传播（不加兜底，红线 5）
 */
import type {
  AccountItem,
  AppItem,
  CollectOutcome,
  GatewayRouteRule,
  GatewayRoutes,
  ImportResult,
  RadarRow,
  RunItem,
  SessionsScan,
} from "./types";

const apiBase = "/api/v1";

/** 非 2xx 响应：server 的 detail 惯例 + HTTP 状态码透传，文案由调用方拼装 */
export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(status: number, detail?: string) {
    super(detail ?? `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  const body = (await resp.json()) as T & { detail?: string };
  if (!resp.ok) throw new ApiError(resp.status, body.detail);
  return body;
}

function post(body?: unknown): RequestInit {
  return {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

/* ---- 账号域 ---- */

export function getAccounts(): Promise<AccountItem[]> {
  return request<AccountItem[]>(`${apiBase}/accounts`);
}

/* ---- 应用域 ---- */

export function getApps(): Promise<AppItem[]> {
  return request<AppItem[]>(`${apiBase}/apps`);
}

export function importApp(
  target: string,
): Promise<{ accounts?: string[]; issues?: string[] }> {
  return request(`${apiBase}/apps/${target}/import`, post());
}

export function importAllApps(): Promise<ImportResult[]> {
  return request<ImportResult[]>(`${apiBase}/apps/import-all`, post());
}

/* ---- 运行域 ---- */

export function getRuns(): Promise<RunItem[]> {
  return request<RunItem[]>(`${apiBase}/runs?limit=200`);
}

export function getPending(): Promise<RunItem[]> {
  return request<RunItem[]>(`${apiBase}/pending?limit=20`);
}

export function createRun(body: { target: string; kind?: string }): Promise<RunItem> {
  return request<RunItem>(`${apiBase}/runs`, post(body));
}

export function claimAllRuns(): Promise<RunItem[]> {
  return request<RunItem[]>(`${apiBase}/runs/claim-all`, post());
}

/* ---- 用量域 ---- */

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

/* ---- 会话域（R5-S1）---- */

/** 扫一次本机会话并入库（只读枚举 + 幂等）；503 = 部署未装配扫描源，detail 直显 */
export function scanAccountSessions(accountId: string): Promise<SessionsScan> {
  return request<SessionsScan>(
    `${apiBase}/accounts/${encodeURIComponent(accountId)}/sessions/scan`,
    post(),
  );
}

/* ---- 网关域（R4-G6）---- */

/** 路由表读取（上抛：设置页转文案展示，不静默——管理面读不到 = 需要被看见） */
export function getGatewayRoutes(): Promise<GatewayRoutes> {
  return request<GatewayRoutes>(`${apiBase}/gateway/routes`);
}

/** 整表替换（声明式配置，无增量 PATCH）：非法表 server 422，detail 直显不加工 */
export function putGatewayRoutes(routes: GatewayRouteRule[]): Promise<GatewayRoutes> {
  return request<GatewayRoutes>(`${apiBase}/gateway/routes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ routes }),
  });
}

/* ---- 系统域 ---- */

/** 容错（语义随函数走）：dev 代理可能不转发 /openapi.json，任何失败 resolve null */
export async function getOpenApiInfo(): Promise<{
  title: string;
  version: string;
} | null> {
  try {
    const body = await request<{ info?: { title?: string; version?: string } }>(
      "/openapi.json",
    );
    return body.info?.title && body.info.version
      ? { title: body.info.title, version: body.info.version }
      : null;
  } catch {
    return null;
  }
}
