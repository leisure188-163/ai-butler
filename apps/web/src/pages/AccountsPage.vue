<script setup lang="ts">
/**
 * 账户页（ADR-010 六页 IA）：9 列矩阵工作台 + 一键领取（n）。
 * headline / 待办栏 / 导入入口已分别迁往仪表盘与平台页；
 * 矩阵交互由 components/MatrixTable.vue 承载，本页只做页头与动作下发。
 */
import { computed, ref, watch } from "vue";
import DeleteAccountDialog from "../components/DeleteAccountDialog.vue";
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
  rename: [accountId: string, alias: string];
  removeAccount: [accountId: string];
}>();

/** 关联重设计 v1：默认平铺表格（一屏看全），按平台分组作为可切换的第二视图。
 * 平台页「查看账户」下钻时强制切到分组视图（归属一眼可见）。 */
type ViewMode = "group" | "flat";
const view = ref<ViewMode>("flat");
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

/** 删除账户确认（2026-11-19）：账户行与关联凭据一并删，凭据条数取契约字段 */
const removeTarget = ref<AccountItem | null>(null);
function askRemove(accountId: string): void {
  removeTarget.value = props.accounts.find((a) => a.account_id === accountId) ?? null;
}
function doRemoveAccount(): void {
  const account = removeTarget.value;
  if (!account) return;
  removeTarget.value = null;
  emit("removeAccount", account.account_id);
}

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
        <p class="page-sub">全部平台 × 账户一屏管理，默认平铺表格——切到分组视图可按平台看归属。</p>
      </div>
      <button
        class="btn btn--primary"
        :disabled="busyTarget !== null || loading || !claimableCount"
        @click="emit('claimAll')"
      >一键领取{{ claimableCount ? `（${claimableCount}）` : "" }}</button>
    </div>
  </header>

  <section class="section">
    <div class="view-bar">
      <div class="segmented" role="group" aria-label="账户视图切换">
        <button
          :class="{ on: view === 'group' }"
          :aria-pressed="view === 'group'"
          aria-label="按平台分组"
          title="按平台分组"
          @click="view = 'group'"
        >
          <svg
            class="seg-icon"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <rect x="2.5" y="2.5" width="4.8" height="4.8" rx="1.2" />
            <rect x="8.7" y="2.5" width="4.8" height="4.8" rx="1.2" />
            <rect x="2.5" y="8.7" width="4.8" height="4.8" rx="1.2" />
            <rect x="8.7" y="8.7" width="4.8" height="4.8" rx="1.2" />
          </svg>
        </button>
        <button
          :class="{ on: view === 'flat' }"
          :aria-pressed="view === 'flat'"
          aria-label="平铺表格"
          title="平铺表格"
          @click="view = 'flat'"
        >
          <svg
            class="seg-icon"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="M2.5 4.2h11M2.5 8h11M2.5 11.8h11" />
          </svg>
        </button>
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
      @rename="(id, alias) => emit('rename', id, alias)"
      @remove="askRemove"
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
      @rename="(id, alias) => emit('rename', id, alias)"
      @remove="askRemove"
    />
  </section>
  <DeleteAccountDialog
    v-if="removeTarget"
    :account="removeTarget"
    :busy="busyTarget !== null"
    @close="removeTarget = null"
    @confirm="doRemoveAccount"
  />
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
/* 图标分段切换：灰底胶囊 + 选中项浅色块（参考知识库列表的视图切换器） */
.segmented { display: inline-flex; gap: 2px; padding: 3px; background: var(--color-surface-2); border-radius: var(--radius-sm); }
.segmented button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 24px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--color-text-muted);
  border-radius: calc(var(--radius-sm) - 1px);
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}
.segmented button:hover { color: var(--color-text); }
.segmented button.on { background: var(--color-surface); color: var(--color-text); box-shadow: var(--shadow-soft); }
.seg-icon { width: 15px; height: 15px; }
</style>
