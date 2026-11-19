/**
 * 运行域 DTO（对应 server routes/runs.py 的 Out 模型）。
 */
import type { WithSignal } from "@/shared/types/base";
import type { contract } from "@/shared/types/contract";

export type RunItem = WithSignal<contract["RunOut"]>;
