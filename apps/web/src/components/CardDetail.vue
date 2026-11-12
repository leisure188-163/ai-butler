<script setup lang="ts">
import type { AccountItem, AppItem } from "../types";
import { earliestExpiry, faceOf, fmtTime, signalSeal } from "../utils";
import BizCard from "./BizCard.vue";

defineProps<{
  account: AccountItem | null;
  app: AppItem | null;
  busy: boolean;
}>();

const emit = defineEmits<{ claim: [target: string] }>();
</script>

<template>
  <div v-if="account && app" class="detail">
    <p class="detail-sign">详情 · {{ app.display }}</p>
    <BizCard
      :issuer="app.display"
      :account-id="account.account_id"
      :level="account.level"
      :signal="account.signal"
      :expires-at="earliestExpiry(account)"
      :face="faceOf(account.account_id)"
    />
    <p class="detail-label">凭据</p>
    <ul v-if="account.credentials.length" class="cred-rows">
      <li v-for="cred in account.credentials" :key="cred.kind" class="cred-row">
        <span class="cred-kind">{{ cred.kind }}</span>
        <span class="cred-sub">{{ cred.level }}</span>
        <span v-if="cred.expires_at" class="cred-exp num">{{ fmtTime(cred.expires_at) }} 到期</span>
        <span class="stamp" :class="`stamp--${cred.signal}`">{{ signalSeal(cred.signal) }}</span>
      </li>
    </ul>
    <p v-else class="quietline">这张卡还没有凭据记录。</p>
    <p v-if="account.evidence.length" class="detail-evidence">
      {{ account.evidence.join("；") }}
    </p>
    <p v-if="account.repair_hint" class="row-fix">建议：{{ account.repair_hint }}</p>
    <button class="btn btn--primary detail-claim" :disabled="busy" @click="emit('claim', app.id)">
      领取
    </button>
  </div>
  <p v-else class="detail-empty">点一张卡，看它的内里。</p>
</template>

<style scoped>
.detail-empty { color: var(--color-text-faint); font-size: var(--text-sm); }

.detail-sign {
  margin: 0 0 var(--space-3);
  font-size: var(--text-xs);
  letter-spacing: 0.18em;
  color: var(--color-text-faint);
}

.detail-label {
  margin: var(--space-4) 0 0;
  font-size: var(--text-xs);
  letter-spacing: 0.18em;
  color: var(--color-text-faint);
}
.cred-rows {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--color-border);
}
.cred-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2) 2px;
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
}
.cred-kind { font-weight: 600; }
.cred-sub { color: var(--color-text-muted); }
.cred-exp {
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  white-space: nowrap;
}
.cred-row .stamp { flex: none; }

.detail-evidence {
  margin: var(--space-3) 0 0;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  line-height: 1.6;
}
.detail-claim { margin-top: var(--space-4); }
</style>
