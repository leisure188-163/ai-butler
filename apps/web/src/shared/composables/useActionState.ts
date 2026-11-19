/**
 * 跨域动作状态（2026-11-20 按业务域分包）：正在执行的目标 + 结果提示。
 *
 * 为什么单独一个 composable：账户/平台/运行三个域的动作各自独立成文件，
 * 但「同一次点击只能有一个动作在跑」「结果提示只报一条」是跨域约束——
 * 状态必须单实例，由壳创建后注入三个域（依赖注入，不让域之间互相 import）。
 */
import { ref } from "vue";

export type ActionMsg = { text: string; tone: "ok" | "warn" };

export function useActionState() {
  const busyTarget = ref<string | null>(null);
  const actionMsg = ref<ActionMsg | null>(null);
  return { busyTarget, actionMsg };
}

export type ActionState = ReturnType<typeof useActionState>;
