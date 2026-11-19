/**
 * 平台域端点（对应 server routes/platforms.py）：名册、接入、同步、未导入清单、自定义平台。
 *
 * 容错语义随函数走：非 2xx 抛 ApiError，网络异常原样传播（红线 5）。
 */
import { apiBase, post, request } from "@/shared/api/http";
import type {
  CustomPlatformDeleted,
  CustomPlatformDraft,
  CustomPlatformRow,
  CustomPlatformSaved,
  ImportResult,
  PlatformCandidate,
  PlatformItem,
  PlatformRemoved,
} from "@/domains/platforms/types";

export function getPlatforms(): Promise<PlatformItem[]> {
  return request<PlatformItem[]>(`${apiBase}/platforms`);
}

export function importPlatform(
  target: string,
): Promise<{ accounts?: string[]; issues?: string[] }> {
  return request(`${apiBase}/platforms/${target}/import`, post());
}

export function importAllPlatforms(includeDocked = false): Promise<ImportResult[]> {
  /* includeDocked=true（2026-11-20）：全量重扫本机客户端——已有账户的平台也重新 dock，
     补上多账号客户端里未入库的账号（幂等回放，不覆盖既有账户）。 */
  const query = includeDocked ? "?include_docked=true" : "";
  return request<ImportResult[]>(`${apiBase}/platforms/import-all${query}`, post());
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
