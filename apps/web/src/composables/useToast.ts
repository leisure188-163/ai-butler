/**
 * 全系统统一提示（2026-11-19 用户裁决）：界面正中弹出、3 秒后自动消失。
 *
 * 为什么做成单例：提示原本是各页各飘一行横幅（账户/平台/仪表盘/用量/设置各一份
 * `action-msg`），同一件事在不同页面长得不一样。这里收成**一个出口**——
 * 各域仍写自己的 msg 状态（语义不动），由 App 壳桥接到本单例，只留一种观感。
 *
 * 纪律：
 * - 只有两态 ok / warn；warn 走 attention 色（不引入红色，用户明确拒绝红横幅）。
 * - 后一条提示覆盖前一条并重置 3 秒计时（不堆叠，避免遮挡中间区域）。
 * - 空文本直接忽略（调用方少写一个 if）。
 */
import { ref } from "vue";

const text = ref("");
const tone = ref<"ok" | "warn">("ok");
const visible = ref(false);
let timer: number | null = null;

export function useToast() {
  function show(message: string, kind: "ok" | "warn" = "ok", ms = 3000) {
    if (!message) return;
    text.value = message;
    tone.value = kind;
    visible.value = true;
    if (timer !== null) window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      visible.value = false;
      timer = null;
    }, ms);
  }

  function hide() {
    if (timer !== null) window.clearTimeout(timer);
    timer = null;
    visible.value = false;
  }

  return { text, tone, visible, show, hide };
}
