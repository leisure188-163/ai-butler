/**
 * 平台名册的展示直译（纯函数、零状态）。
 *
 * 从 `pages/PlatformsPage.vue` 拆出（2026-11-19，文件长度红线）：类型/能力/接入前提/
 * 账户数都是「契约字段 → 人话」的直译；能不能接、怎么排班这类判定仍归 core，
 * 这里只做词表映射，不判语义（红线 2 端零映射）。
 */
import type { PlatformItem } from "@/shared/types";

export function capabilityText(kind: string): string {
  if (kind === "provision.run") return "领取";
  if (kind === "health.check") return "体检";
  if (kind.startsWith("usage")) return "用量";
  return kind;
}

/** 主表只出白话能力；session.import 等协议字样留在详情 */
export function visibleCaps(platform: PlatformItem): string[] {
  return platform.capabilities.filter(
    (c) => c === "provision.run" || c === "health.check" || c.startsWith("usage"),
  );
}

/** 平台类型直译（词表 = core PLATFORM_KINDS；空=未申报） */
export function kindText(kind: string): string {
  if (kind === "web") return "网页版";
  if (kind === "client") return "客户端";
  return "—";
}

/** 接入前提：只按契约字段直译，不在这里判定能不能接 */
export function accessHint(platform: PlatformItem): string {
  if (platform.kind === "client") return "需本机已安装并登录该客户端";
  if (platform.kind === "web") return "需先在浏览器里登录该平台";
  return "需先登录对应客户端或浏览器";
}

export function accountCount(platform: PlatformItem): number {
  if (platform.account_ids?.length) return platform.account_ids.length;
  return platform.account_id ? 1 : 0;
}
