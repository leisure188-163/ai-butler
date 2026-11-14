<script setup lang="ts">
/**
 * 账户页（ADR-013 六页 IA）：9 列矩阵工作台 + 一键领取（n）。
 * headline / 待办栏 / 导入入口已分别迁往仪表盘与应用页；
 * 矩阵交互由 components/MatrixTable.vue 承载，本页只做页头与动作下发。
 */
import { computed } from "vue";
import MatrixTable from "../components/MatrixTable.vue";
import type { AccountItem, AppItem, RadarRow, RunItem } from "../types";

const props = defineProps<{
  accounts: AccountItem[];
  apps: AppItem[];
  radar: RadarRow[];
  runs: RunItem[];
  busyTarget: string | null;
  msg: { text: string; tone: "ok" | "warn" } | null;
  loading: boolean;
  loadError: string;
}>();

const emit = defineEmits<{
  claim: [target: string];
  health: [target: string];
  claimMany: [targets: string[]];
  claimAll: [];
}>();

/* 一键领取计数：申报了 provision.run 且已导入的应用才计数（不虚报） */
const claimableCount = computed(
  () => props.apps.filter((a) => a.account_id && a.capabilities.includes("provision.run")).length,
);
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">账户</h1>
        <p class="page-sub">全部应用 × 账户一屏管理。</p>
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
    <MatrixTable
      :accounts="accounts"
      :apps="apps"
      :radar="radar"
      :runs="runs"
      :busy-target="busyTarget"
      @claim="emit('claim', $event)"
      @health="emit('health', $event)"
      @claim-many="emit('claimMany', $event)"
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
</style>
