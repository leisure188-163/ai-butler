<script setup lang="ts">
/**
 * 账户页（ADR-010 六页 IA）：9 列矩阵工作台 + 一键领取（n）。
 * headline / 待办栏 / 导入入口已分别迁往仪表盘与平台页；
 * 矩阵交互由 components/MatrixTable.vue 承载，本页只做页头与动作下发。
 */
import { computed, ref, watch } from "vue";
import MatrixTable from "../components/MatrixTable.vue";
import AccountGrouped from "../components/AccountGrouped.vue";
import type { AccountItem, PlatformItem, RadarRow, RunItem } from "../types";

const props = defineProps<{
  accounts: AccountItem[];
  platforms: PlatformItem[];
  radar: RadarRow[];
  runs: RunItem[];
  busyTarget: string | null;
  /** 从平台页「查看账户」下钻带来的平台编码（分组视图预筛选） */
  initialPlatform?: string | null;
  msg: { text: string; tone: "ok" | "warn" } | null;
  loading: boolean;
  loadError: string;
}>();

const emit = defineEmits<{
  claim: [target: string];
  health: [target: string];
  claimMany: [targets: string[]];
  claimAll: [];
  scanSessions: [accountId: string];
  repair: [target: string, accountId: string];
}>();

/** 关联重设计 v1：默认按平台分组，平铺矩阵作为可切换的第二视图。
 * 平台页「查看账户」下钻时强制切到分组视图（归属一眼可见）。 */
type ViewMode = "group" | "flat";
const view = ref<ViewMode>("group");
const focusPlatform = ref<string | null>(props.initialPlatform ?? null);
watch(
  () => props.initialPlatform,
  (code) => {
    if (code) {
      focusPlatform.value = code;
      view.value = "group";
    }
  },
);

/* 一键领取计数：申报了 provision.run 且已导入的平台才计数（不虚报） */
const claimableCount = computed(
  () => props.platforms.filter((a) => a.account_id && a.capabilities.includes("provision.run")).length,
);
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">账户管理</h1>
        <p class="page-sub">全部平台 × 账户一屏管理，默认按平台分组——每个账户都有归属。</p>
      </div>
      <button
        class="btn btn--primary"
        :disabled="busyTarget !== null || loading || !claimableCount"
        @click="emit('claimAll')"
      >一键领取{{ claimableCount ? `（${claimableCount}）` : "" }}</button>
    </div>
  </header>

  <p
    v-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <section class="section">
    <div class="view-bar">
      <span class="view-label">视图</span>
      <div class="segmented" role="group" aria-label="账户视图切换">
        <button :class="{ on: view === 'group' }" :aria-pressed="view === 'group'" @click="view = 'group'">按平台分组</button>
        <button :class="{ on: view === 'flat' }" :aria-pressed="view === 'flat'" @click="view = 'flat'">平铺表格</button>
      </div>
    </div>

    <AccountGrouped
      v-if="view === 'group'"
      :accounts="accounts"
      :platforms="platforms"
      :radar="radar"
      :runs="runs"
      :busy-target="busyTarget"
      :initial-platform="focusPlatform"
      @claim="emit('claim', $event)"
      @health="emit('health', $event)"
      @claim-many="emit('claimMany', $event)"
      @scan-sessions="emit('scanSessions', $event)"
      @repair="(target, id) => emit('repair', target, id)"
    />
    <MatrixTable
      v-else
      :accounts="accounts"
      :platforms="platforms"
      :radar="radar"
      :runs="runs"
      :busy-target="busyTarget"
      :initial-platform="focusPlatform"
      @claim="emit('claim', $event)"
      @health="emit('health', $event)"
      @claim-many="emit('claimMany', $event)"
      @scan-sessions="emit('scanSessions', $event)"
    />
  </section>
</template>

<style scoped>
.head { padding-top: var(--space-2); }
.head-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.section { margin-top: var(--space-6); }
.view-bar { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
.view-label { font-size: var(--text-xs); color: var(--color-text-muted); }
.segmented { display: inline-flex; gap: 2px; padding: 3px; background: var(--color-surface-2); border-radius: var(--radius-sm); }
.segmented button {
  border: 0;
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-size: var(--text-sm);
  padding: 4px 14px;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.segmented button.on { background: var(--color-surface); color: var(--color-text); font-weight: 600; box-shadow: var(--shadow-soft); }
</style>
