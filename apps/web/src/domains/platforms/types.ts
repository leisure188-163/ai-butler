/**
 * 平台域 DTO（对应 server routes/platforms.py 的 Out 模型）：名册、未导入候选、自定义平台。
 */
import type { contract } from "@/shared/types/contract";

export type PlatformItem = contract["PlatformOut"];
export type PlatformCandidate = contract["PlatformCandidateOut"];
export type PlatformRemoved = contract["PlatformRemovedOut"];
export type ImportResult = contract["ImportOut"];

/** 平台编辑载荷（UI 只提交契约字段；端不做业务判定） */
export type PlatformPatch = {
  platform_name?: string | null;
  active?: boolean;
  times?: string[] | null;
  /** 平台图标（2026-11-19）：96px PNG data URI；"" = 清空（回落身份色点/内置图标） */
  icon?: string | null;
  /** 接入源连接事实（ADR-033）：只对 origin=user 生效 */
  base_url?: string;
  protocol?: string;
  models?: string[];
};

/** 接入源创建草稿（ADR-033）：relay/local/api 型上游 */
export type ProviderDraft = {
  platform_code: string;
  platform_name: string;
  kind: string;
  base_url: string;
  protocol: string;
  models: string[];
  credential_kinds: string[];
};

/** 自定义平台（2026-11-18）：草稿 = 用户填的表单形状；目录行 = 已登记的自定义平台 */
export type CustomPlatformDraft = contract["CustomPlatformIn"];
export type CustomPlatformRow = contract["CustomPlatformOut"];
export type CustomPlatformSaved = contract["CustomPlatformSaved"];
export type CustomPlatformDeleted = contract["CustomPlatformDeleted"];

/** 平台检索条件（2026-11-18）：纯前端筛选，不是契约字段 —— 端不做业务判定 */
export type PlatformQuery = {
  keyword: string;
  status: "all" | "active" | "inactive";
  kind: "all" | "web" | "client" | "relay" | "local" | "api";
  sort: "code" | "name" | "accounts";
};
