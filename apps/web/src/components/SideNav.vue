<script setup lang="ts">
import type { PageName } from "../types";

defineProps<{
  active: PageName;
  alertCount: number;
  loading: boolean;
  loadedAt: string;
}>();

const emit = defineEmits<{ navigate: [page: PageName]; refresh: [] }>();

const navItems: PageName[] = ["账号", "用量", "记录", "设置"];
</script>

<template>
  <aside class="sidenav">
    <div class="brand">
      <span class="brand-name">AI 智能助手管家 <span class="brand-latin">Butler</span></span>
      <span class="brand-line">AI 账号管家</span>
    </div>

    <nav class="nav" aria-label="主导航">
      <button
        v-for="item in navItems"
        :key="item"
        class="nav-item"
        :class="{ 'nav-item--active': active === item }"
        :aria-current="active === item ? 'page' : undefined"
        @click="emit('navigate', item)"
      >
        {{ item }}
        <span
          v-if="item === '账号' && alertCount > 0"
          class="badge"
        >{{ alertCount > 99 ? "99+" : alertCount }}</span>
      </button>
    </nav>

    <div class="nav-foot">
      <button class="btn btn--ghost" :disabled="loading" @click="emit('refresh')">刷新</button>
      <span v-if="loadedAt" class="nav-foot-time num">{{ loadedAt }}</span>
    </div>
  </aside>
</template>

<style scoped>
.sidenav {
  width: var(--sidebar-w);
  flex: none;
  position: sticky;
  top: 0;
  height: 100vh;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  padding: var(--space-6) var(--space-4);
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
}
.brand {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--space-2);
  margin-bottom: var(--space-6);
}
.brand-name { font-size: var(--text-lg); font-weight: 650; }
.brand-latin { font-size: var(--text-xs); color: var(--color-text-muted); font-weight: 400; }
.brand-line { font-size: var(--text-xs); color: var(--color-text-faint); }

.nav { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.nav-item {
  appearance: none;
  border: none;
  background: none;
  display: flex;
  align-items: center;
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  font: inherit;
  font-size: var(--text-md);
  text-align: left;
  cursor: pointer;
  transition: background var(--motion-base), color var(--motion-base);
}
.nav-item:hover { color: var(--color-ink); background: var(--color-bg); }
.nav-item--active {
  position: relative;
  color: var(--color-ink);
  background: var(--color-bg);
}
.nav-item--active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 2px;
  background: var(--color-accent-bright);
}
.badge {
  margin-left: auto;
  min-width: 20px;
  text-align: center;
  background: var(--color-ink);
  color: var(--color-on-ink);
  font-size: var(--text-xs);
  line-height: 1;
  padding: 4px 6px;
  border-radius: var(--radius-chip);
  font-variant-numeric: tabular-nums;
}

.nav-foot {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-1);
}
.nav-foot-time { color: var(--color-text-faint); font-size: var(--text-xs); }

@media (max-width: 900px) {
  .sidenav {
    position: static;
    height: auto;
    width: 100%;
    flex-direction: row;
    align-items: center;
    gap: var(--space-4);
    padding: var(--space-3) var(--space-4);
    border-right: none;
    border-bottom: 1px solid var(--color-border);
  }
  .brand { margin-bottom: 0; padding: 0; }
  .brand-line { display: none; }
  .nav { flex-direction: row; align-items: center; }
  .nav-item { width: auto; }
  .nav-foot { margin-left: auto; padding: 0; }
  .nav-foot-time { display: none; }
}
</style>
