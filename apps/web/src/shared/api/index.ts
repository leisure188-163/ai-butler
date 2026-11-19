/**
 * 端点访问聚合入口（对齐 server api.py「聚合器只做装配」纪律）：
 * 只 re-export 各域端点，不写任何 URL 或响应形状。域内实现见 domains/<域>/api.ts。
 *
 * 只用一个域的文件优先直连域（@/domains/<域>/api），跨域文件（App、页面壳）用本入口。
 */
export * from "./http";
export * from "@/domains/accounts/api";
export * from "@/domains/platforms/api";
export * from "@/domains/runs/api";
export * from "@/domains/usage/api";
export * from "@/domains/settings/api";
