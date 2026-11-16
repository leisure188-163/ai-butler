<script setup lang="ts">
/**
 * 仪表盘右栏（v6.3 布局改版）：快捷入口 + 班次时刻。
 * 快捷入口 = 纯导航（emit navigate），不做跨页动作，零新端点；
 * 班次时刻 = apps 真实 schedule_times 并集排序，下一个未来时刻高亮，
 * 无排班如实留白（红线 2：不编造状态）。
 */
import { computed } from "vue";
import type { AppItem, PageName } from "../types";

const props = defineProps<{ apps: AppItem[] }>();

const emit = defineEmits<{ navigate: [page: PageName] }>();

const tiles: { page: PageName; title: string; sub: string; icon: string }[] = [
  { page: "应用", title: "导入应用", sub: "把本机客户端接进来", icon: "plus" },
  { page: "账户", title: "去领取", sub: "手动领取今日班次", icon: "check" },
  { page: "流量", title: "去采集", sub: "拉取余额与额度快照", icon: "drop" },
  { page: "日志", title: "看日志", sub: "每次动作都有台账", icon: "list" },
];

const shiftTimes = computed(() =>
  [...new Set(props.apps.flatMap((a) => a.schedule_times))]
    .filter((t) => /^\d{1,2}:\d{2}$/.test(t))
    .sort(),
);

const nowMinutes = computed(() => {
  const now = new Date();
  return now.getHours() * 60 + now.getMinutes();
});

function toMinutes(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}
</script>

<template>
  <section class="section section--flush" aria-label="快捷入口">
    <h2 class="section-title">快捷入口</h2>
    <div class="quick-grid">
      <button
        v-for="t in tiles"
        :key="t.page"
        class="quick-tile"
        type="button"
        @click="emit('navigate', t.page)"
      >
        <span class="quick-icon" aria-hidden="true">
          <svg v-if="t.icon === 'plus'" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M8 3v10M3 8h10" /></svg>
          <svg v-else-if="t.icon === 'check'" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6" /><path d="m5.5 8 1.8 1.8L10.7 6" /></svg>
          <svg v-else-if="t.icon === 'drop'" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M8 2.5s4 4.6 4 7.4a4 4 0 0 1-8 0c0-2.8 4-7.4 4-7.4Z" /></svg>
          <svg v-else viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M5.5 4h8M5.5 8h8M5.5 12h8" /><circle cx="2.5" cy="4" r="0.8" fill="currentColor" stroke="none" /><circle cx="2.5" cy="8" r="0.8" fill="currentColor" stroke="none" /><circle cx="2.5" cy="12" r="0.8" fill="currentColor" stroke="none" /></svg>
        </span>
        <span class="quick-main">
          <span class="quick-title">{{ t.title }}</span>
          <span class="quick-sub">{{ t.sub }}</span>
        </span>
      </button>
    </div>
  </section>

  <section class="section section--flush" aria-label="班次时刻">
    <h2 class="section-title">班次时刻</h2>
    <div class="sheet shift-sheet">
      <p v-if="!shiftTimes.length" class="shift-empty">
        还没有应用排班——到「应用」页为应用排班
      </p>
      <template v-else>
        <p
          v-for="t in shiftTimes"
          :key="t"
          class="shift-row"
          :class="{ 'shift-row--next': toMinutes(t) > nowMinutes && shiftTimes.find((x) => toMinutes(x) > nowMinutes) === t }"
        >
          <span class="shift-time mono">{{ t }}</span>
          <span v-if="toMinutes(t) > nowMinutes" class="shift-tag">未到</span>
          <span v-else class="shift-tag shift-tag--past">已过</span>
        </p>
      </template>
    </div>
  </section>
</template>

<style scoped>
.section--flush { margin-top: var(--space-5); }
.section--flush:first-child { margin-top: 0; }

.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
}
.quick-tile {
  appearance: none;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-soft);
  font: inherit;
  text-align: left;
  padding: var(--space-3);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
  min-width: 0;
  transition: border-color var(--motion-base), transform var(--motion-fast) var(--ease-out);
}
.quick-tile:hover { border-color: var(--color-accent); }
.quick-tile:active { transform: scale(0.97); }
.quick-icon {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: var(--color-accent-weak);
  color: var(--color-accent);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.quick-icon svg { width: 15px; height: 15px; }
.quick-main { min-width: 0; display: flex; flex-direction: column; }
.quick-title { font-size: var(--text-sm); font-weight: 600; color: var(--color-ink); }
.quick-sub {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.shift-sheet { padding: var(--space-2) var(--space-4); }
.shift-row {
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
}
.shift-row:last-child { border-bottom: none; }
.shift-row--next .shift-time { color: var(--color-accent); font-weight: 650; }
.shift-time { font-size: var(--text-md); }
.shift-tag {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--color-accent);
}
.shift-tag--past { color: var(--color-text-faint); }
.shift-empty { margin: 0; padding: var(--space-2) 0; font-size: var(--text-sm); color: var(--color-text-muted); }
</style>
