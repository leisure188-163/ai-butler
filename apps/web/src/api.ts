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
  AccountDeleted,
  AccountItem,
  PlatformItem,
  PlatformCandidate,
  PlatformRemoved,
  CollectOutcome,
  CustomPlatformDraft,
  CustomPlatformDeleted,
  CustomPlatformRow,
  CustomPlatformSaved,
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
  // 代理/网关在服务不可达时常回 HTML 或空响应：先读文本再解析，避免
  // resp.json() 的 SyntaxError 冒充业务错误。非 JSON 显式抛 ApiError（红线 5 仍 throw）
  const text = await resp.text();
  let body: unknown = null;
  if (text.trim()) {
    try {
      body = JSON.parse(text);
    } catch {
      throw new ApiError(resp.status, `非 JSON 响应：${text.slice(0, 120)}`);
    }
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, (body as { detail?: string } | null)?.detail);
  }
  return (body ?? {}) as T;
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

/** 改账户别名（ADR-030）：空串 = 清除，显示回落到连接器给的名称。
 * account_id 含冒号（platform:code），必须 encode 后再进路径。 */
export function setAccountAlias(accountId: string, alias: string): Promise<AccountItem> {
  return request<AccountItem>(`${apiBase}/accounts/${encodeURIComponent(accountId)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ alias }),
  });
}

/* ---- 平台域 ---- */

export function getPlatforms(): Promise<PlatformItem[]> {
  return request<PlatformItem[]>(`${apiBase}/platforms`);
}

export function importPlatform(
  target: string,
): Promise<{ accounts?: string[]; issues?: string[] }> {
  return request(`${apiBase}/platforms/${target}/import`, post());
}

export function importAllPlatforms(): Promise<ImportResult[]> {
  return request<ImportResult[]>(`${apiBase}/platforms/import-all`, post());
}

/** 同步平台（ADR-031）：重扫连接器把 manifest 事实写回名册，返回同步后的名册。
 * 平台表被清空 / 连接器升级后用；「接入」只导账户、不建名册。
 * 2026-11-19 起：只自动纳本机客户端，网页版留在「未导入」清单里人工导入。 */
export function resyncPlatforms(): Promise<PlatformItem[]> {
  return request<PlatformItem[]>(`${apiBase}/platforms/resync`, post());
}

/** 未导入的平台（2026-11-19）：连接器存在但名册里没有的连接器平台。
 * 网页版不自动纳册，由用户在这份清单里按需导入。 */
export function getUnimportedPlatforms(): Promise<PlatformCandidate[]> {
  return request<PlatformCandidate[]>(`${apiBase}/platforms/unimported`);
}

/** 人工导入单个平台（2026-11-19）：纳册 + 立即接入，一步完成。
 * 平台已存在时等同「重新接入」；网页版走这里才进名册。 */
export function adoptPlatform(target: string): Promise<ImportResult> {
  return request<ImportResult>(
    `${apiBase}/platforms/${encodeURIComponent(target)}/adopt`,
    post(),
  );
}

/** 移出名册（2026-11-19）：只删平台事实行，账户/台账/凭据保留；
 * 之后可在「未导入的平台」重新导入（按 platform_code 自动归位）。 */
export function removePlatform(code: string): Promise<PlatformRemoved> {
  return request<PlatformRemoved>(`${apiBase}/platforms/${encodeURIComponent(code)}`, {
    method: "DELETE",
  });
}

/** 编辑平台信息（2026-11-18 / 11-19）：显示名 / 启用状态 / 调度执行时间 / 平台图标。
 * 只传要改的键；times=null 恢复默认、[] 不排班；icon="" 清空图标（回落身份色点）。 */
export function patchPlatform(
  target: string,
  body: {
    platform_name?: string | null;
    active?: boolean;
    times?: string[] | null;
    icon?: string | null;
  },
): Promise<PlatformItem> {
  return request<PlatformItem>(`${apiBase}/platforms/${target}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** 改调度执行时间（2026-11-18）：times=null 恢复平台默认；[] = 该平台不排班。
 * 写后 server 立即热替换调度，返回生效值；非 2xx 原样抛 ApiError（红线 5）。 */
export function updateSchedule(
  target: string,
  times: string[] | null,
): Promise<PlatformItem> {
  return request<PlatformItem>(`${apiBase}/platforms/${target}/schedule`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ times }),
  });
}

/** 自定义平台目录（2026-11-18）：已登记的内置清单之外的平台（前端据此标「自定义」） */
export function getCustomPlatforms(): Promise<CustomPlatformRow[]> {
  return request<CustomPlatformRow[]>(`${apiBase}/platforms/custom`);
}

/** 新建/更新自定义平台：server 校验 → 落成声明式连接器 → 热加载。
 * 422 = 声明不完整（detail 直显）；409 = 编码被内置占用；非 2xx 原样抛 ApiError。 */
export function saveCustomPlatform(
  body: CustomPlatformDraft,
): Promise<CustomPlatformSaved> {
  return request<CustomPlatformSaved>(`${apiBase}/platforms/custom`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** 删除自定义平台：名册自动落 deprecated，不再排班（内置平台只能停用，409）。 */
export function deleteCustomPlatform(code: string): Promise<CustomPlatformDeleted> {
  return request<CustomPlatformDeleted>(`${apiBase}/platforms/custom/${code}`, {
    method: "DELETE",
  });
}

/** 删除账户（2026-11-19）：账户行 + 关联凭据一并删除，不留脏数据。 */
export function deleteAccount(accountId: string): Promise<AccountDeleted> {
  return request<AccountDeleted>(`${apiBase}/accounts/${encodeURIComponent(accountId)}`, {
    method: "DELETE",
  });
}

/* ---- 运行域 ---- */

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
