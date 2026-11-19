/**
 * 设置域 DTO：网关路由管理面（契约派生）+ 本机 UI 偏好（主题/刷新）。
 *
 * 网关校验单源在 core（UI 不复写规则，422 detail 直显）。
 */
import type { contract } from "@/shared/types/contract";

export type GatewayRouteRule = contract["RouteRuleOut"];
export type GatewayRoutes = contract["GatewayRoutesOut"];

export type ThemeName = "system" | "qinglan" | "paper" | "dark" | "mist";

export interface Settings {
  autoRefresh: boolean;
  intervalSec: number;
  theme: ThemeName;
}
