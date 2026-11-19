<script setup lang="ts">
/**
 * 顶部提示条（2026-11-19 用户裁决：页面顶部弹出，3 秒自动消失，全系统统一）。
 *
 * 固定在整个视口顶部、横向居中，不吃点击（pointer-events: none，只有卡片本身可交互）；
 * 显隐与计时全在 useToast 单例里，本组件只负责画。
 */
import { useToast } from "@/shared/composables/useToast";

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
  /* 页面顶部居中（2026-11-19 用户二次裁决：不要盖住页面中间的内容）；
     18px 与页头留一口气，横向仍居中，纵向贴顶。 */
  place-items: start center;
  padding-top: 18px;
  pointer-events: none;
  z-index: 900;
}
.toast {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  max-width: min(560px, 78vw);
  padding: var(--space-3) var(--space-4);
  /* 底色走主题的弱色档（ok-weak），与页面同一色系；不再用纯纸白 + 粗绿边——
     那套白底深绿在暖纸/晨雾/青岚里都显得像外来控件（2026-11-19 用户反馈）。 */
  background: var(--color-ok-weak);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  font-size: var(--text-sm);
  pointer-events: auto;
  backdrop-filter: blur(3px);
}
.toast--warn {
  background: var(--color-attention-weak);
}
.toast-mark {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-chip);
  background: var(--color-ok);
  flex: none;
}
.toast--warn .toast-mark {
  background: var(--color-attention);
}
.toast-text {
  color: var(--color-ok-ink);
  line-height: 1.5;
  word-break: break-word;
}
.toast--warn .toast-text {
  color: var(--color-attention-ink);
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.98);
}
</style>
