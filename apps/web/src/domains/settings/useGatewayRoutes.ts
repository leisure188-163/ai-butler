/**
 * 网关路由域动作（R4-G6，conventions/4 §2.4）：读取 + 整表替换。
 * loading/saving/routesMsg 归本域；ApiError 转 UI 文案，网络异常同样转述
 * （管理面读不到 = 需要被看见，不是静默降级——文案如实说够不到服务）。
 */
import { ref } from "vue";
import * as api from "@/shared/api";
import type { GatewayRouteRule } from "@/shared/types";

export function useGatewayRoutes() {
  const routes = ref<GatewayRouteRule[]>([]);
  const takesEffect = ref("");
  const loadingRoutes = ref(false);
  const savingRoutes = ref(false);
  const routesMsg = ref<{ text: string; tone: "ok" | "warn" } | null>(null);

  async function loadRoutes() {
    loadingRoutes.value = true;
    try {
      const body = await api.getGatewayRoutes();
      routes.value = body.routes;
      takesEffect.value = body.takes_effect;
      routesMsg.value = null;
    } catch (e) {
      routes.value = [];
      routesMsg.value =
        e instanceof api.ApiError
          ? { text: e.detail ?? `路由表读取失败（HTTP ${e.status}）`, tone: "warn" }
          : { text: "路由表读取失败——够不到本机服务。", tone: "warn" };
    } finally {
      loadingRoutes.value = false;
    }
  }

  /** 整表替换：成功回填 server 返回的规范表并如实转述生效时机；失败文案随 422 detail */
  async function saveRoutes(next: GatewayRouteRule[]): Promise<boolean> {
    savingRoutes.value = true;
    routesMsg.value = null;
    try {
      const body = await api.putGatewayRoutes(next);
      routes.value = body.routes;
      takesEffect.value = body.takes_effect;
      routesMsg.value = {
        text: `已保存 ${body.routes.length} 条规则。${body.takes_effect}`,
        tone: "ok",
      };
      return true;
    } catch (e) {
      routesMsg.value =
        e instanceof api.ApiError
          ? { text: e.detail ?? `保存失败（HTTP ${e.status}）`, tone: "warn" }
          : { text: "保存失败——够不到本机服务。", tone: "warn" };
      return false;
    } finally {
      savingRoutes.value = false;
    }
  }

  return { routes, takesEffect, loadingRoutes, savingRoutes, routesMsg, loadRoutes, saveRoutes };
}
