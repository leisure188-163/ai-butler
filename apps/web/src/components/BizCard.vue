<script setup lang="ts">
import { computed } from "vue";
import type { Signal } from "../types";
import { fmtTime, signalSeal } from "../utils";

const props = withDefaults(
  defineProps<{
    issuer: string;
    accountId: string;
    level?: string | null;
    signal: Signal;
    expiresAt: string | null;
    face: number;
    reveal?: boolean;
    selected?: boolean;
  }>(),
  { level: null, reveal: false, selected: false },
);

const emit = defineEmits<{ activate: [] }>();

const initial = computed(() => props.issuer.slice(0, 1) || "卡");
const seal = computed(() => signalSeal(props.signal));
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
      <span class="bc-badge" aria-hidden="true">{{ initial }}</span>
      <span class="bc-issuer">{{ issuer }}</span>
      <span v-if="level" class="bc-level">{{ level }}</span>
    </header>
    <p class="bc-number">{{ accountId }}</p>
    <footer class="bc-bottom">
      <span class="bc-chip" aria-hidden="true"></span>
      <span class="bc-valid num">有效期至 {{ fmtTime(expiresAt) }}</span>
      <span class="bc-seal">{{ seal }}</span>
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
  color: var(--face-text);
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
.bizcard:hover { transform: translateY(-3px); box-shadow: var(--shadow-lift); }
.bizcard:focus-visible { outline-offset: 3px; }

/* 卡面身份色：hi→lo 渐变对（135deg 光源；色相 token 唯一来源） */
.bizcard--face-1 { background: linear-gradient(135deg, var(--card-face-1-hi), var(--card-face-1-lo)); }
.bizcard--face-2 { background: linear-gradient(135deg, var(--card-face-2-hi), var(--card-face-2-lo)); }
.bizcard--face-3 { background: linear-gradient(135deg, var(--card-face-3-hi), var(--card-face-3-lo)); }
.bizcard--face-4 { background: linear-gradient(135deg, var(--card-face-4-hi), var(--card-face-4-lo)); }
.bizcard--face-5 { background: linear-gradient(135deg, var(--card-face-5-hi), var(--card-face-5-lo)); }
.bizcard--face-6 { background: linear-gradient(135deg, var(--card-face-6-hi), var(--card-face-6-lo)); }

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

.bc-top { display: flex; align-items: center; gap: var(--space-2); }
.bc-badge {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.22);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-sm);
  font-weight: 700;
  flex: none;
}
.bc-issuer {
  font-size: var(--text-md);
  font-weight: 650;
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.bc-level {
  margin-left: auto;
  flex: none;
  font-size: var(--text-xs);
  border: 1px solid rgba(255, 255, 255, 0.55);
  border-radius: var(--radius-sm);
  padding: 1px 7px;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

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

.bc-bottom { display: flex; align-items: center; gap: var(--space-3); }
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
.bc-valid {
  font-size: var(--text-xs);
  opacity: 0.85;
  white-space: nowrap;
  margin-left: auto;
}
.bc-seal {
  flex: none;
  font-size: var(--text-xs);
  font-weight: 700;
  border: 1.5px solid currentColor;
  border-radius: 4px;
  padding: 1px 6px;
  letter-spacing: 0.12em;
  line-height: 1.5;
}
.bizcard--ok .bc-seal { color: var(--face-seal-ok); }
.bizcard--notice .bc-seal { color: var(--face-seal-notice); }
.bizcard--attention .bc-seal { color: var(--face-seal-attention); }
.bizcard--danger .bc-seal { color: var(--face-seal-danger); }
.bizcard--quiet .bc-seal { color: var(--face-seal-quiet); }
</style>
