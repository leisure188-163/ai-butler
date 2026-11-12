<script setup lang="ts">
import type { PageName } from "../types";

defineProps<{
  active: PageName;
  alertCount: number;
  loading: boolean;
  loadedAt: string;
}>();

const emit = defineEmits<{ navigate: [page: PageName]; refresh: [] }>();

const overviewItems: PageName[] = ["首页", "卡包", "记录"];
</script>

<template>
  <aside class="sidenav">
    <div class="brand">
      <span class="brand-chip" aria-hidden="true"></span>
      <span class="brand-name">卡包</span>
      <span class="brand-latin">Kabao</span>
    </div>

    <nav class="nav" aria-label="主导航">
      <p class="nav-group-label">总览</p>
      <button
        v-for="item in overviewItems"
        :key="item"
        class="nav-item"
        :class="{ 'nav-item--active': active === item }"
        :aria-current="active === item ? 'page' : undefined"
        @click="emit('navigate', item)"
      >
        {{ item }}
      </button>

      <p class="nav-group-label">管理</p>
      <button
        class="nav-item"
        :class="{ 'nav-item--active': active === '提醒' }"
        :aria-current="active === '提醒' ? 'page' : undefined"
        @click="emit('navigate', '提醒')"
      >
        提醒
        <span v-if="alertCount > 0" class="badge">{{ alertCount > 99 ? "99+" : alertCount }}</span>
      </button>
      <button
        class="nav-item"
        :class="{ 'nav-item--active': active === '设置' }"
        :aria-current="active === '设置' ? 'page' : undefined"
        @click="emit('navigate', '设置')"
      >
        设置
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
  align-items: baseline;
  gap: var(--space-2);
  padding: 0 var(--space-2);
  margin-bottom: var(--space-6);
}
.brand-chip {
  width: 20px;
  height: 15px;
  border-radius: 4px;
  align-self: center;
  background: linear-gradient(135deg, var(--chip-gold-hi), var(--chip-gold-lo));
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12);
}
.brand-name { font-size: var(--text-lg); font-weight: 650; }
.brand-latin { font-size: var(--text-xs); color: var(--color-text-muted); }

.nav { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.nav-group-label {
  margin: var(--space-4) 0 var(--space-1);
  padding: 0 var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}
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
  .nav { flex-direction: row; align-items: center; }
  .nav-group-label { display: none; }
  .nav-item { width: auto; }
  .nav-foot { margin-left: auto; padding: 0; }
  .nav-foot-time { display: none; }
}
</style>
