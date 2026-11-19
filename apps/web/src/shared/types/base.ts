/**
 * 跨域共享的 UI 基础类型（2026-11-20 按业务域分包）。
 *
 * DTO 形状一律派生自 packages/sdk 契约（红线 2/4，禁止手写字段）；本文件只放
 * 与具体业务域无关的 UI 词表与通用结构，域内 DTO 见 domains/<域>/types.ts。
 */
import type { components } from "@butler/sdk";

type Contract = components["schemas"];

/** core 出产的五分类信号（UI 谓词只认它，端零映射：页面不认识 Status/HealthLevel 本身） */
export type Signal = "ok" | "notice" | "attention" | "danger" | "quiet";

/** signal 窄化包装：除 signal 外的形状全部继承契约 */
export type WithSignal<T> = Omit<T, "signal"> & { signal: Signal };

/** A3-01 v2 六页 IA：页面名字即路由键 */
export type PageName =
  | "签到概览"
  | "平台管理"
  | "账户管理"
  | "用量管理"
  | "运行日志"
  | "系统设置";

/** 行操作项（2026-11-18）：操作列直连 ≤2 个，其余进「更多」下拉 */
export type RowAction = {
  key: string;
  label: string;
  /** 悬停说明（2026-11-19）：动作名不足以表达语义时补一句，如「重新接入」 */
  title?: string;
  /** 图标化动作（2026-11-19）：有值时渲染图标按钮，label 只作 aria-label/title 用 */
  icon?: "edit" | "refresh" | "dots";
  danger?: boolean;
  disabled?: boolean;
};

/** 契约 schemas 的类型入口（域 types 各自再窄化，避免每处重复 import） */
export type Schemas = Contract;
