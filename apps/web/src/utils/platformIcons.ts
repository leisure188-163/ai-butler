/**
 * 平台官方图标映射（2026-11-19）。
 *
 * 来源：四家从本机已安装客户端里取的真实图标（Qoder CN `resources/app-icon.ico`、
 * 豆包 `app/icon.ico`、Trae CN 主程序 exe 的 256px 图标、WorkBuddy
 * `resources/icon.png`），AgentRouter 取官方文档站标识。全部本地化到
 * `assets/platforms/`，运行时不依赖网络。新增平台时把 png 放进去、这里加一行即可；
 * 没有登记的平台回落 PlatformBadge 的身份色点。
 */
import agentrouter from "../assets/platforms/agentrouter.png";
import doubao from "../assets/platforms/doubao.png";
import qoder from "../assets/platforms/qoder_cn.png";
import trae from "../assets/platforms/trae_cn.png";
import workbuddy from "../assets/platforms/workbuddy_cn.png";

const ICONS: Record<string, string> = {
  agentrouter,
  doubao_cn: doubao,
  qoder_cn: qoder,
  trae_cn: trae,
  workbuddy_cn: workbuddy,
};

export function platformIcon(platformId: string): string | null {
  return ICONS[platformId] ?? null;
}
