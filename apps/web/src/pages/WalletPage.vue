<script setup lang="ts">
import { computed, ref } from "vue";
import BizCard from "../components/BizCard.vue";
import type { AccountItem, AppItem } from "../types";
import { earliestExpiry, faceOf, fmtTime } from "../utils";

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
const selected = computed(() => selectedId.value);
const selectedAccount = computed(() =>
  selectedId.value ? props.accounts.find((a) => a.account_id === selectedId.value) ?? null : null,
);

const importableCount = computed(() => props.apps.filter((a) => !a.account_id).length);
const claimableCount = computed(() => props.apps.filter((a) => a.account_id).length);

function toggle(accountId: string) {
  selectedId.value = selectedId.value === accountId ? null : accountId;
}
</script>

<template>
  <header class="head">
    <h1 class="page-title">卡包</h1>
    <p class="page-sub">应用接入与卡的体检明细。</p>
  </header>

  <p
    v-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <section class="section" aria-label="应用">
    <div class="section-head">
      <h2 class="section-title">应用</h2>
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
    <ul v-if="apps.length" class="rows panel">
      <li v-for="app in apps" :key="app.id" class="row">
        <span
          class="lamp"
          :class="app.account_id ? 'lamp--ok' : 'lamp--quiet'"
          aria-hidden="true"
        ></span>
        <div class="row-main">
          <p class="row-title">
            {{ app.display }}
            <span class="row-sub mono">{{ app.id }}</span>
          </p>
          <p class="row-sub">
            {{ app.account_id ? `已导入 · ${app.account_id}` : "未导入——先导入才能领取" }}
            <template v-if="app.schedule_times.length">
              · 时间表 {{ app.schedule_times.join(" ") }}
            </template>
          </p>
        </div>
        <span class="row-actions">
          <button class="btn" :disabled="busyTarget !== null" @click="emit('import', app.id)">导入</button>
          <button
            class="btn btn--primary"
            :disabled="busyTarget !== null || !app.account_id"
            @click="emit('claim', app.id)"
          >领取</button>
        </span>
      </li>
    </ul>
    <p v-else class="quietline">还没有接入任何应用。</p>
  </section>

  <section class="section" aria-label="卡">
    <h2 class="section-title">卡</h2>
    <div v-if="accounts.length" class="wall">
      <BizCard
        v-for="account in accounts"
        :key="account.account_id"
        :issuer="apps.find((x) => x.account_id === account.account_id)?.display ?? '未关联应用'"
        :account-id="account.account_id"
        :signal="account.signal"
        :expires-at="earliestExpiry(account)"
        :face="faceOf(account.account_id)"
        :selected="selectedId === account.account_id"
        @activate="toggle(account.account_id)"
      />
    </div>
    <p v-else class="quietline">还没有卡——导入应用后自动生成。</p>

    <div v-if="selected" class="detail panel">
      <p class="detail-title">
        {{ apps.find((x) => x.account_id === selected)?.display ?? "未关联应用" }}
        <span class="row-sub mono">{{ selected }}</span>
        <span class="row-sub">· {{ accounts.find((a) => a.account_id === selected)?.level }}</span>
      </p>
      <ul class="creds">
        <li v-for="cred in selectedAccount?.credentials ?? []" :key="cred.kind" class="cred">
          <span class="lamp lamp--mini" :class="`lamp--${cred.signal}`" aria-hidden="true"></span>
          <span>{{ cred.kind }}</span>
          <span class="row-sub num" v-if="cred.expires_at">有效期至 {{ fmtTime(cred.expires_at) }}</span>
          <span class="row-sub">{{ cred.level }}</span>
        </li>
      </ul>
      <p v-if="selectedAccount && selectedAccount.evidence.length" class="row-sub">
        {{ selectedAccount.evidence.join("；") }}
      </p>
      <p v-if="selectedAccount?.repair_hint" class="row-fix">
        建议：{{ selectedAccount.repair_hint }}
      </p>
    </div>
  </section>
</template>

<style scoped>
.head { padding-top: var(--space-2); }

.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.section-head .section-title { margin-bottom: 0; }

.wall {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: var(--space-5);
  justify-items: center;
}

.detail {
  margin-top: var(--space-4);
  padding: var(--space-4) var(--space-5);
}
.detail-title { margin: 0; font-size: var(--text-md); }
.creds {
  list-style: none;
  margin: var(--space-3) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.cred {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  font-size: var(--text-sm);
}
.lamp--mini { width: 6px; height: 6px; align-self: center; }
</style>
