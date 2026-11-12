<script setup lang="ts">
import type { Signal } from "../types";
import { fmtTime } from "../utils";

withDefaults(
  defineProps<{
    issuer: string;
    accountId: string;
    signal: Signal;
    expiresAt: string | null;
    face: number;
    reveal?: boolean;
    selected?: boolean;
  }>(),
  { reveal: false, selected: false },
);

const emit = defineEmits<{ activate: [] }>();
</script>

<template>
  <article
    class="bizcard"
    :class="[
      `bizcard--face-${face}`,
      `bizcard--${signal}`,
      { 'bizcard--reveal': reveal, 'bizcard--selected': selected },
    ]"
    @click="emit('activate')"
  >
    <header class="bc-top">
      <span class="bc-issuer">{{ issuer }}</span>
      <span class="bc-lamp" :class="`bc-lamp--${signal}`" aria-hidden="true"></span>
    </header>
    <p class="bc-number">{{ accountId }}</p>
    <footer class="bc-bottom">
      <span class="bc-chip" aria-hidden="true"></span>
      <span class="bc-valid num">有效期至 {{ fmtTime(expiresAt) }}</span>
    </footer>
  </article>
</template>

<style scoped>
.bizcard {
  position: relative;
  box-sizing: border-box;
  aspect-ratio: 1.586;
  width: 100%;
  max-width: 340px;
  border-radius: var(--radius-lg);
  padding: var(--space-4) var(--space-5);
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition:
    transform var(--motion-base) var(--ease-out),
    box-shadow var(--motion-base) var(--ease-out);
}
.bizcard:hover { transform: translateY(-6px); box-shadow: var(--shadow-lift); }
.bizcard:focus-visible { outline-offset: 3px; }

/* 状态脊：卡顶 5px 色条，色相由 core signal 分类决定 */
.bizcard::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 5px;
}
.bizcard--ok::before { background: var(--color-ok); }
.bizcard--notice::before { background: var(--color-notice); }
.bizcard--attention::before { background: var(--color-attention); }
.bizcard--danger::before { background: var(--color-danger); }
.bizcard--quiet::before { background: var(--color-quiet); }

.bizcard--face-1 { background: var(--card-face-1); }
.bizcard--face-2 { background: var(--card-face-2); }
.bizcard--face-3 { background: var(--card-face-3); }
.bizcard--face-4 { background: var(--card-face-4); }
.bizcard--face-5 { background: var(--card-face-5); }
.bizcard--face-6 { background: var(--card-face-6); }

.bizcard--selected {
  outline: 2px solid var(--color-accent-bright);
  outline-offset: 3px;
}

/* 唯一 orchestrated moment：首页卡扇错落揭示（reduced-motion 由 tokens 归零） */
.bizcard--reveal {
  animation: card-in var(--motion-reveal) var(--ease-out) both;
  animation-delay: calc(var(--i, 0) * 60ms);
}
@keyframes card-in {
  from { opacity: 0; transform: translateY(10px) scale(0.98); }
  to { opacity: 1; transform: none; }
}

.bc-top { display: flex; justify-content: space-between; align-items: center; }
.bc-issuer {
  font-size: var(--text-sm);
  font-weight: 600;
  letter-spacing: 0.02em;
  opacity: 0.92;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 卡面上的灯用提亮档（深卡面上保可见），色相仍一一对应 signal 分类 */
.bc-lamp { width: 9px; height: 9px; border-radius: 50%; box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.25); flex: none; }
.bc-lamp--ok { background: #52d69e; }
.bc-lamp--notice { background: #f0c869; }
.bc-lamp--attention { background: #f7a06b; }
.bc-lamp--danger { background: #f28b8b; }
.bc-lamp--quiet { background: rgba(255, 255, 255, 0.55); }

.bc-number {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-lg);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.35);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bc-bottom { display: flex; justify-content: space-between; align-items: flex-end; gap: var(--space-3); }
.bc-chip {
  width: 34px;
  height: 24px;
  border-radius: 5px;
  position: relative;
  flex: none;
  background: linear-gradient(135deg, var(--chip-gold-hi), var(--chip-gold-lo));
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12);
}
.bc-chip::before {
  content: "";
  position: absolute;
  left: 8px;
  right: 8px;
  top: 6px;
  bottom: 6px;
  border: 1px solid rgba(0, 0, 0, 0.15);
  border-radius: 2px;
}
.bc-valid { font-size: var(--text-xs); opacity: 0.85; white-space: nowrap; }
</style>
