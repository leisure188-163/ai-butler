/**
 * 契约类型入口（红线 2/4 单源）：所有域 DTO 都从这里取 @butler/sdk 生成类型，
 * 禁止手写字段形状——server 改字段，vue-tsc 当场报错。
 */
import type { components } from "@butler/sdk";

export type contract = components["schemas"];
