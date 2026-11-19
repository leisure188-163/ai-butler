<script setup lang="ts">
import { computed } from "vue";
import type { PageName } from "@/shared/types";

const props = defineProps<{
  active: PageName;
  alertCount: number;
  loading: boolean;
  loadedAt: string;
  theme?: string;
}>();

const emit = defineEmits<{ navigate: [page: PageName]; refresh: [] }>();

/* 青岚山水主题的侧栏插画底色（system 已在 useSettings 解析为 mist，不会误显） */
const isQinglan = computed(() => props.theme === "qinglan");

/* ADR-010：六页平铺（hash 直链不变），签到概览默认；角标挂签到概览。
   v6.1 侧栏视觉分组：新页（网关/迁移等）挂对应组即可，IA 不动（D3 补记）
   2026-11-19：显示名「仪表盘」→「签到概览」（hash 仍 #/dashboard，收藏夹不失效） */
const navGroups: { label: string; items: PageName[] }[] = [
  { label: "总览", items: ["签到概览"] },
  { label: "运营", items: ["平台管理", "账户管理", "用量管理", "运行日志"] },
  { label: "系统", items: ["系统设置"] },
];

/* v6 功能图标（线性 16px，stroke=currentColor 随文字色）——
   功能性视觉锚点，非装饰（DESIGN-DECISIONS D2 v6） */
const icons: Record<PageName, string> = {
  签到概览: "M2 9.5 8 4l6 5.5V14a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z M8 10v5",
  平台管理: "M3 3h4v4H3zM9 3h4v4H9zM3 9h4v4H3zM9 9h4v4H9z",
  账户管理: "M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2.5 14c.7-2.6 2.9-4 5.5-4s4.8 1.4 5.5 4",
  用量管理: "M1 10l3-5 3 6 2.5-4 2 3h3.5",
  运行日志: "M4 2h8a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z M6 6h4M6 9h4M6 12h3",
  系统设置: "M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 1.5l1 2 2.2-.5 1.4 1.9-.9 2 .9 2-1.4 1.9-2.2-.5-1 2H7l-1-2-2.2.5L2.4 11l.9-2-.9-2L3.8 5 6 5.5l1-2z",
};
</script>

<template>
  <aside class="sidenav" :class="{ 'sidenav--qinglan': isQinglan }">
    <!-- 青岚山水：侧栏下半部湖泊松林插画（仅青岚主题显示，纯 SVG 可落地） -->
    <svg
      v-if="isQinglan"
      class="side-scene"
      viewBox="0 0 240 420"
      preserveAspectRatio="xMidYMax slice"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="ql-hill1" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--hill-far)" /><stop offset="1" stop-color="#b4d8c7" />
        </linearGradient>
        <linearGradient id="ql-hill2" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--hill-mid)" /><stop offset="1" stop-color="#7fb99f" />
        </linearGradient>
        <linearGradient id="ql-hill3" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#5ea184" /><stop offset="1" stop-color="var(--hill-near)" />
        </linearGradient>
        <linearGradient id="ql-lake" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--lake-top)" /><stop offset="1" stop-color="var(--lake-bottom)" />
        </linearGradient>
        <linearGradient id="ql-mist" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#eef6f2" stop-opacity="0" /><stop offset="1" stop-color="#eef6f2" stop-opacity=".92" />
        </linearGradient>
      </defs>
      <path d="M0 168 Q34 140 68 158 Q98 120 132 150 Q166 118 202 148 Q222 136 240 150 L240 262 L0 262 Z" fill="url(#ql-hill1)" />
      <path d="M0 196 Q40 166 82 190 Q120 156 160 186 Q200 160 240 188 L240 268 L0 268 Z" fill="url(#ql-hill2)" opacity=".92" />
      <path d="M0 268 L0 236 l7 -20 6 20 5 -26 6 26 6 -16 6 16 5 -22 7 22 6 -14 6 14 7 -28 7 28 6 -18 6 18 6 -22 7 22 6 -12 6 12 7 -26 7 26 6 -16 6 16 6 -20 7 20 6 -14 6 14 7 -22 7 22 6 -16 6 16 L240 268 Z" fill="url(#ql-hill3)" />
      <rect x="0" y="268" width="240" height="152" fill="url(#ql-lake)" />
      <g opacity=".16" transform="translate(0,536) scale(1,-1)">
        <path d="M0 268 L0 236 l7 -20 6 20 5 -26 6 26 6 -16 6 16 5 -22 7 22 6 -14 6 14 7 -28 7 28 6 -18 6 18 6 -22 7 22 6 -12 6 12 7 -26 7 26 6 -16 6 16 6 -20 7 20 6 -14 6 14 7 -22 7 22 6 -16 6 16 L240 268 Z" fill="#2f6e56" />
      </g>
      <g stroke="#9ccdb8" stroke-width="1" opacity=".5" fill="none">
        <path d="M20 300 q12 -4 26 0 M120 312 q14 -4 30 0 M60 330 q12 -4 26 0 M150 346 q14 -4 30 0 M30 360 q12 -4 26 0" />
      </g>
      <rect x="0" y="120" width="240" height="150" fill="url(#ql-mist)" opacity=".5" />
    </svg>

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
            v-if="item === '签到概览' && alertCount > 0"
            class="badge"
          >{{ alertCount > 99 ? "99+" : alertCount }}</span>
        </button>
      </div>
    </nav>

    <div v-if="isQinglan" class="side-quote" aria-hidden="true">
      <span class="sq-1">更好的自己</span>
      <span class="sq-2">从今天开始</span>
      <span class="sq-by">—— 每日签到，稳步向前</span>
    </div>

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
  background: var(--color-sidebar);
  border-right: 1px solid var(--color-border);
  overflow: hidden;
}
/* 青岚山水：插画铺在侧栏下半部，导航浮在其上 */
.side-scene {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  height: 52%;
  pointer-events: none;
  z-index: 0;
}
.sidenav > :not(.side-scene) { position: relative; z-index: 1; }
.side-quote {
  margin: 0 0 var(--space-3);
  padding: var(--space-2) 0;
  text-align: center;
  color: var(--quote-ink, #2f6e56);
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.5);
}
.sq-1 { display: block; font-size: var(--text-xs); font-weight: 650; letter-spacing: 0.06em; }
.sq-2 { display: block; font-size: var(--text-sm); font-weight: 750; margin: 2px 0; }
.sq-by { display: block; font-size: 10px; opacity: 0.8; }
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
