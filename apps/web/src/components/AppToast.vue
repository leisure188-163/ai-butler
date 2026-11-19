<script setup lang="ts">
/**
 * 居中提示条（2026-11-19 用户裁决：界面中间弹出，3 秒自动消失，全系统统一）。
 *
 * 位置固定在整个视口正中，不吃点击（pointer-events: none，只有卡片本身可交互）；
 * 显隐与计时全在 useToast 单例里，本组件只负责画。
 */
import { useToast } from "../composables/useToast";

/* 解构到顶层绑定：模板只对顶层 ref 自动解包，写 `toast.visible` 拿到的是 Ref 对象
   （v-if 恒真、`:class` 渲染成 `toast--[object Object]`）——踩过一次，别再改写。 */
const { visible, text, tone } = useToast();
</script>

<template>
  <Transition name="toast">
    <div v-if="visible" class="toast-host" role="status" aria-live="polite">
      <div class="toast" :class="`toast--${tone}`">
        <span class="toast-mark" aria-hidden="true" />
        <span class="toast-text">{{ text }}</span>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.toast-host {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  pointer-events: none;
  z-index: 900;
}
.toast {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  max-width: min(560px, 78vw);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-left: 3px solid var(--color-ok);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  font-size: var(--text-sm);
  pointer-events: auto;
}
.toast--warn {
  border-left-color: var(--color-attention);
}
.toast-mark {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-chip);
  background: var(--color-ok);
  flex: none;
}
.toast--warn .toast-mark {
  background: var(--color-attention);
}
.toast-text {
  color: var(--color-text);
  line-height: 1.5;
  word-break: break-word;
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}
</style>
