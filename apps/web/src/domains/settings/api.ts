/**
 * 设置域端点（对应 server routes/gateway.py 与系统信息）：网关路由表、接口文档元信息。
 */
import { apiBase, request, sendJson } from "@/shared/api/http";
import type { GatewayRouteRule, GatewayRoutes } from "@/domains/settings/types";

/** 路由表读取（上抛：设置页转文案展示，不静默——管理面读不到 = 需要被看见） */
export function getGatewayRoutes(): Promise<GatewayRoutes> {
  return request<GatewayRoutes>(`${apiBase}/gateway/routes`);
}

/** 整表替换（声明式配置，无增量 PATCH）：非法表 server 422，detail 直显不加工 */
export function putGatewayRoutes(routes: GatewayRouteRule[]): Promise<GatewayRoutes> {
  return request<GatewayRoutes>(`${apiBase}/gateway/routes`, sendJson("PUT", { routes }));
}

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
