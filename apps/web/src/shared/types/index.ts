/**
 * DTO 聚合入口（对齐 server api.py「聚合器只做装配」纪律）：
 * 只 re-export，不写任何字段形状。域内实现见 domains/<域>/types.ts。
 *
 * 需要单域类型的文件优先直连域（@/domains/<域>/types），跨域文件用本入口。
 */
export * from "./base";
export * from "@/domains/accounts/types";
export * from "@/domains/platforms/types";
export * from "@/domains/runs/types";
export * from "@/domains/usage/types";
export * from "@/domains/settings/types";
