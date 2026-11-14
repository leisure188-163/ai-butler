<script setup lang="ts">
/**
 * 账户详情面板（六页 IA，ADR-013）：矩阵行下展开的体检明细。
 * 保留凭据清单/证据/repair_hint/能力驱动按钮。
 * 动作按钮按能力矩阵渲染（AppOut.capabilities，端零映射）：
 * provision.run = 领取；health.check = 体检（R3 网页通道）。
 */
import { computed } from "vue";
import type { AccountItem, AppItem } from "../types";
import { earliestExpiry, faceOf, fmtTime, signalText } from "../utils";
import AppBadge from "./AppBadge.vue";

const props = defineProps<{
  account: AccountItem | null;
  app: AppItem | null;
  busy: boolean;
}>();

const emit = defineEmits<{
  claim: [target: string];
  health: [target: string];
  close: [];
}>();

const hasClaim = computed(() => props.app?.capabilities.includes("provision.run") ?? false);
const hasHealth = computed(() => props.app?.capabilities.includes("health.check") ?? false);
</script>

<template>
  <div v-if="account && app" class="detail">
    <div class="detail-head">
      <AppBadge :name="app.display" :color-index="faceOf(account.account_id)" />
      <span class="detail-id mono">{{ account.account_id }}</span>
      <button class="detail-close" aria-label="收起详情" @click="emit('close')">✕</button>
    </div>

    <p class="detail-status">
      <span class="tag" :class="`tag--${account.signal}`">{{ signalText(account.signal) }}</span>
      <span v-if="earliestExpiry(account)" class="row-sub num">
        凭据最早 {{ fmtTime(earliestExpiry(account)) }} 到期
      </span>
    </p>

    <p class="detail-label">凭据</p>
    <ul v-if="account.credentials.length" class="cred-rows">
      <li v-for="cred in account.credentials" :key="cred.kind" class="cred-row">
        <span class="cred-kind">{{ cred.kind }}</span>
        <span class="row-sub">{{ cred.level }}</span>
        <span v-if="cred.expires_at" class="row-sub num cred-exp">
          {{ fmtTime(cred.expires_at) }} 到期
        </span>
        <span class="tag" :class="`tag--${cred.signal}`">{{ signalText(cred.signal) }}</span>
      </li>
    </ul>
    <p v-else class="quietline">该账户还没有凭据。</p>

    <p v-if="account.evidence.length" class="detail-evidence">
      {{ account.evidence.join("；") }}
    </p>
    <p v-if="account.repair_hint" class="row-fix">建议：{{ account.repair_hint }}</p>

    <span v-if="hasClaim || hasHealth" class="row-actions detail-actions">
      <button
        v-if="hasClaim"
        class="btn btn--primary"
        :disabled="busy"
        @click="emit('claim', app.id)"
      >领取</button>
      <button
        v-if="hasHealth"
        class="btn"
        :class="hasClaim ? 'btn--ghost' : 'btn--primary'"
        :disabled="busy"
        @click="emit('health', app.id)"
      >体检</button>
    </span>
  </div>
  <p v-else class="detail-empty">在矩阵里点一行账户，看它的凭据与体检详情。</p>
</template>

<style scoped>
.detail-empty { color: var(--color-text-faint); font-size: var(--text-sm); }

.detail-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.detail-id {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-close {
  appearance: none;
  border: none;
  background: none;
  color: var(--color-text-faint);
  font-size: var(--text-md);
  cursor: pointer;
  padding: 0 var(--space-1);
  margin-left: auto;
}
.detail-close:hover { color: var(--color-ink); }

.detail-status {
  margin: var(--space-2) 0 0;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.detail-label {
  margin: var(--space-3) 0 0;
  font-size: var(--text-xs);
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
.cred-exp { margin-left: auto; white-space: nowrap; }
.cred-row .tag { flex: none; align-self: center; }

.detail-evidence {
  margin: var(--space-3) 0 0;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  line-height: 1.6;
}
.detail-actions { margin-top: var(--space-3); }
</style>
