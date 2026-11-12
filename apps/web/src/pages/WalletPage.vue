<script setup lang="ts">
import { computed, ref } from "vue";
import BizCard from "../components/BizCard.vue";
import CardDetail from "../components/CardDetail.vue";
import type { AccountItem, AppItem } from "../types";
import { earliestExpiry, faceOf } from "../utils";

const props = defineProps<{
  apps: AppItem[];
  accounts: AccountItem[];
  busyTarget: string | null;
  msg: { text: string; tone: "ok" | "warn" } | null;
}>();

const emit = defineEmits<{
  import: [target: string];
  claim: [target: string];
  importAll: [];
  claimAll: [];
}>();

const selectedId = ref<string | null>(null);
const selectedAccount = computed(() =>
  selectedId.value ? props.accounts.find((a) => a.account_id === selectedId.value) ?? null : null,
);
const selectedApp = computed(() => {
  const acc = selectedAccount.value;
  return acc ? props.apps.find((x) => x.account_id === acc.account_id) ?? null : null;
});

const emptyApps = computed(() => props.apps.filter((a) => !a.account_id));
const importableCount = computed(() => emptyApps.value.length);
const claimableCount = computed(() => props.apps.filter((a) => a.account_id).length);

const stats = computed(() => {
  const unwell = props.accounts.filter((a) => a.signal !== "ok").length;
  const base = `${props.apps.length} 应用 · ${props.accounts.length} 卡`;
  return unwell ? `${base} · ${unwell} 待留意` : base;
});

function toggle(accountId: string) {
  selectedId.value = selectedId.value === accountId ? null : accountId;
}
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">卡包</h1>
        <p class="page-sub">{{ stats }}</p>
      </div>
      <span class="row-actions">
        <button
          class="btn"
          :disabled="busyTarget !== null || !importableCount"
          @click="emit('importAll')"
        >一键导入{{ importableCount ? `（${importableCount}）` : "" }}</button>
        <button
          class="btn btn--primary"
          :disabled="busyTarget !== null || !claimableCount"
          @click="emit('claimAll')"
        >一键领取{{ claimableCount ? `（${claimableCount}）` : "" }}</button>
      </span>
    </div>
  </header>

  <p
    v-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <div class="rack">
    <section class="stack" aria-label="卡">
      <BizCard
        v-for="account in accounts"
        :key="account.account_id"
        :issuer="apps.find((x) => x.account_id === account.account_id)?.display ?? '未关联应用'"
        :account-id="account.account_id"
        :level="account.level"
        :signal="account.signal"
        :expires-at="earliestExpiry(account)"
        :face="faceOf(account.account_id)"
        :selected="selectedId === account.account_id"
        @activate="toggle(account.account_id)"
      />
      <button
        v-for="app in emptyApps"
        :key="app.id"
        class="slot"
        :disabled="busyTarget !== null"
        @click="emit('import', app.id)"
      >
        <span class="slot-plus" aria-hidden="true">＋</span>
        导入 {{ app.display }}
      </button>
      <p v-if="!accounts.length && !emptyApps.length" class="quietline">
        还没有接入任何应用——有连接器装好后会出现在这里。
      </p>
    </section>

    <aside class="side" aria-label="卡详情">
      <CardDetail
        :account="selectedAccount"
        :app="selectedApp"
        :busy="busyTarget !== null"
        @claim="emit('claim', $event)"
      />
    </aside>
  </div>
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

/* 钱包架：左卡堆 + 右详情，细线分隔（不浮板） */
.rack {
  margin-top: var(--space-6);
  display: flex;
  align-items: flex-start;
}
.stack {
  flex: 1.6;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3);
  padding-right: var(--space-6);
}
.side {
  flex: 1;
  min-width: 260px;
  border-left: 1px solid var(--color-border);
  padding-left: var(--space-6);
  position: sticky;
  top: var(--space-6);
}

.slot {
  box-sizing: border-box;
  width: 100%;
  max-width: 340px;
  aspect-ratio: 1.586;
  border: 1.5px dashed var(--slot-dash);
  border-radius: var(--radius-lg);
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-size: var(--text-sm);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  cursor: pointer;
  transition:
    border-color var(--motion-base),
    color var(--motion-base);
}
.slot:hover:not(:disabled) { border-color: var(--color-accent); color: var(--color-accent); }
.slot:disabled { opacity: 0.45; cursor: not-allowed; }
.slot-plus { font-size: var(--text-xl); line-height: 1; }

/* 窄屏：详情下沉为卡堆之下的展开区 */
@media (max-width: 900px) {
  .rack { flex-direction: column; }
  .stack { padding-right: 0; }
  .side {
    position: static;
    width: 100%;
    border-left: none;
    border-top: 1px solid var(--color-border);
    padding-left: 0;
    padding-top: var(--space-4);
    margin-top: var(--space-2);
  }
}
</style>
