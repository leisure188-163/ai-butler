<script setup lang="ts">
import type { PageName } from "../types";

defineProps<{
  active: PageName;
  alertCount: number;
  loading: boolean;
  loadedAt: string;
}>();

const emit = defineEmits<{ navigate: [page: PageName]; refresh: [] }>();

/* ADR-010：六页平铺（hash 直链不变），仪表盘默认；角标挂仪表盘。
   v6.1 侧栏视觉分组：新页（网关/迁移等）挂对应组即可，IA 不动（D3 补记） */
const navGroups: { label: string; items: PageName[] }[] = [
  { label: "总览", items: ["仪表盘"] },
  { label: "运营", items: ["平台管理", "账户管理", "用量管理", "运行日志"] },
  { label: "系统", items: ["系统设置"] },
];

/* v6 功能图标（线性 16px，stroke=currentColor 随文字色）——
   功能性视觉锚点，非装饰（DESIGN-DECISIONS D2 v6） */
const icons: Record<PageName, string> = {
  仪表盘: "M2 9.5 8 4l6 5.5V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z M8 10v5",
  平台管理: "M3 3h4v4H3zM9 3h4v4H9zM3 9h4v4H3zM9 9h4v4H9z",
  账户管理: "M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2.5 14c.7-2.6 2.9-4 5.5-4s4.8 1.4 5.5 4",
  用量管理: "M1 10l3-5 3 6 2.5-4 2 3h3.5",
  运行日志: "M4 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z M6 6h4M6 9h4M6 12h3",
  系统设置: "M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 1.5l1 2 2.2-.5 1.4 1.9-.9 2 .9 2-1.4 1.9-2.2-.5-1 2H7l-1-2-2.2.5L2.4 11l.9-2-.9-2L3.8 5 6 5.5l1-2z",
};
</script>

<template>
  <aside class="sidenav">
    <div class="brand">
      <span class="brand-mark" aria-hidden="true">B</span>
      <span class="brand-name">AI 智能助手管家 <span class="brand-latin">Butler</span></span>
    </div>

    <nav class="nav" aria-label="主导航">
      <div v-for="group in navGroups" :key="group.label" class="nav-group">
        <p class="nav-group-label" aria-hidden="true">{{ group.label }}</p>
        <button
          v-for="item in group.items"
          :key="item"
          class="nav-item"
          :class="{ 'nav-item--active': active === item }"
          :aria-current="active === item ? 'page' : undefined"
          @click="emit('navigate', item)"
        >
          <svg
            class="nav-icon"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path :d="icons[item]" />
          </svg>
          {{ item }}
          <span
            v-if="item === '仪表盘' && alertCount > 0"
            class="badge"
          >{{ alertCount > 99 ? "99+" : alertCount }}</span>
        </button>
      </div>
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
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-2);
  margin-bottom: var(--space-6);
}
.brand-mark {
  flex: none;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  background: var(--color-ink);
  color: var(--color-on-ink);
  border-radius: 8px;
  font-size: var(--text-md);
  font-weight: 700;
}
.brand-name {
  font-size: var(--text-md);
  font-weight: 650;
  white-space: nowrap;
  line-height: 1.3;
}
.brand-latin { display: block; font-size: var(--text-xs); color: var(--color-text-muted); font-weight: 400; }

.nav { flex: 1; display: flex; flex-direction: column; gap: var(--space-4); }
.nav-group { display: flex; flex-direction: column; gap: 2px; }
.nav-group-label {
  margin: 0 0 var(--space-1);
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
  gap: var(--space-3);
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
.nav-icon { flex: none; width: 16px; height: 16px; opacity: 0.75; }
.nav-item--active .nav-icon { opacity: 1; }
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
  /* 顶条两行网格：品牌+刷新一行，六项导航一行（窄屏横向滚动，不与品牌重叠） */
  .sidenav {
    position: static;
    height: auto;
    width: 100%;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      "brand foot"
      "nav nav";
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    border-right: none;
    border-bottom: 1px solid var(--color-border);
  }
  .brand { grid-area: brand; margin-bottom: 0; padding: 0; }
  .nav {
    grid-area: nav;
    flex-direction: row;
    align-items: center;
    flex-wrap: wrap;            /* 窄屏换行铺满，不靠横滚藏菜单 */
    min-width: 0;
    overflow-x: visible;
    gap: var(--space-1);
  }
  .nav-group { flex-direction: row; align-items: center; gap: var(--space-1); }
  .nav-group-label { display: none; } /* 窄屏顶条保持平铺，分组不占横向空间 */
  .nav-item { width: auto; white-space: nowrap; padding: var(--space-2); }
  .nav-foot { grid-area: foot; margin-left: 0; padding: 0; }
  .nav-foot-time { display: none; }
}
</style>
