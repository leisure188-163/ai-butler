<script setup lang="ts">
import { computed } from "vue";
import type { AccountItem, CredentialItem, PageName, RunItem } from "../types";
import { fmtTime } from "../utils";

const props = defineProps<{
  pending: RunItem[];
  accounts: AccountItem[];
}>();

const emit = defineEmits<{ navigate: [page: PageName] }>();

const expiring = computed<{ account: AccountItem; cred: CredentialItem }[]>(() =>
  props.accounts.flatMap((account) =>
    account.credentials
      .filter((c) => c.signal === "notice")
      .map((cred) => ({ account, cred })),
  ),
);

const unwell = computed(() => props.accounts.filter((a) => a.signal !== "ok"));

const total = computed(() => props.pending.length + expiring.value.length + unwell.value.length);
</script>

<template>
  <header class="head">
    <h1 class="page-title">提醒</h1>
    <p class="page-sub">
      {{ total > 0 ? `${total} 项需要关注` : "一切正常，没有需要你操心的事。" }}
    </p>
  </header>

  <template v-if="total > 0">
    <section v-if="pending.length" class="section" aria-label="待处理">
      <h2 class="section-title">待处理</h2>
      <ul class="rows panel">
        <li v-for="item in pending" :key="item.id" class="row">
          <span class="lamp" :class="`lamp--${item.signal}`" aria-hidden="true"></span>
          <div class="row-main">
            <p class="row-title">
              {{ item.account_id }}
              <span class="row-sub mono">{{ item.kind }} · {{ item.target }}</span>
            </p>
            <p v-if="item.repair_reason" class="row-fix">{{ item.repair_reason }}</p>
            <details v-if="item.evidence.length" class="fold">
              <summary>查看详情</summary>
              <ul class="evidence">
                <li v-for="(ev, i) in item.evidence" :key="i">
                  {{ ev.summary }}<code v-if="ev.raw_code"> [{{ ev.raw_code }}]</code>
                </li>
              </ul>
            </details>
          </div>
          <span class="row-time">{{ fmtTime(item.started_at) }}</span>
        </li>
      </ul>
    </section>

    <section v-if="expiring.length" class="section" aria-label="即将到期">
      <h2 class="section-title">即将到期</h2>
      <ul class="rows panel">
        <li v-for="{ account, cred } in expiring" :key="`${account.account_id}-${cred.kind}`" class="row">
          <span class="lamp lamp--notice" aria-hidden="true"></span>
          <div class="row-main">
            <p class="row-title">{{ account.account_id }}</p>
            <p class="row-sub">
              {{ cred.kind }} · 有效期至 <span class="num">{{ fmtTime(cred.expires_at) }}</span>
            </p>
          </div>
          <span class="row-actions">
            <button class="btn btn--ghost" @click="emit('navigate', '卡包')">去卡包</button>
          </span>
        </li>
      </ul>
    </section>

    <section v-if="unwell.length" class="section" aria-label="需要留意">
      <h2 class="section-title">需要留意</h2>
      <ul class="rows panel">
        <li v-for="account in unwell" :key="account.account_id" class="row">
          <span class="lamp" :class="`lamp--${account.signal}`" aria-hidden="true"></span>
          <div class="row-main">
            <p class="row-title">{{ account.account_id }}</p>
            <p v-if="account.evidence.length" class="row-sub">{{ account.evidence.join("；") }}</p>
            <p v-if="account.repair_hint" class="row-fix">建议：{{ account.repair_hint }}</p>
          </div>
          <span class="row-actions">
            <button class="btn btn--ghost" @click="emit('navigate', '卡包')">去卡包</button>
          </span>
        </li>
      </ul>
    </section>
  </template>

  <p v-else class="quietline">等有到期、异常或待处理的事项，这里会第一时间汇总。</p>
</template>

<style scoped>
.head { padding-top: var(--space-2); }
</style>
