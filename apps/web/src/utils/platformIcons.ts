/**
 * 平台图标解析（2026-11-19 裁决：图标跟着平台数据走）。
 *
 * 读取顺序：**平台行自带 icon**（`plat_platform.icon`，同步时从本机客户端探测写入、
 * 自定义平台可由用户上传）→ 内置 assets 兜底（老库/尚未同步过一次的平台）→ null
 * （PlatformBadge 回落身份色点）。
 *
 * assets 里的五张 png 是最初的本地化取图（豆包/Qoder CN/Trae CN/WorkBuddy 的客户端
 * 真实图标 + AgentRouter 官方标识）；有了数据库图标后它们只作兜底，不再当唯一来源。
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

export function platformIcon(
  platform: { id: string; icon?: string | null } | null | undefined,
): string | null {
  if (!platform) return null;
  if (platform.icon) return platform.icon; // 数据图标优先：换机器/换版本重同步会自动刷新
  return ICONS[platform.id] ?? null;
}
