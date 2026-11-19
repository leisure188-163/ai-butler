<script setup lang="ts">
/**
 * 账户详情面板（六页 IA，ADR-010）：矩阵行下展开的体检明细。
 * 保留凭据清单/证据/repair_hint/能力驱动按钮。
 * 动作按钮按能力矩阵渲染（AppOut.capabilities，端零映射）：
 * provision.run = 领取；health.check = 体检（R3 网页通道）。
 */
import { computed, ref, watch } from "vue";
import type { AccountItem, PlatformItem } from "../types";
import { earliestExpiry, faceOf, fmtTime, signalText } from "../utils";
import PlatformBadge from "./PlatformBadge.vue";

/** 会话 location 是绝对路径：卡片里只显示末段（目录名/文件名），全名 title 提示 */
function sessionLabel(location: string): string {
  const parts = location.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? location;
}

const props = defineProps<{
  account: AccountItem | null;
  platform: PlatformItem | null;
  busy: boolean;
}>();

const emit = defineEmits<{
  claim: [target: string];
  health: [target: string];
  scanSessions: [accountId: string];
  rename: [accountId: string, alias: string];
  close: [];
}>();

/* 别名草稿跟随当前账户；账户换人时重置，避免把上一张卡的输入带到下一张 */
const aliasDraft = ref("");
watch(
  () => props.account?.account_id,
  () => {
    aliasDraft.value = props.account?.alias ?? "";
  },
  { immediate: true },
);
const aliasDirty = computed(
  () => aliasDraft.value.trim() !== (props.account?.alias ?? ""),
);

function saveAlias() {
  if (!props.account) return;
  emit("rename", props.account.account_id, aliasDraft.value.trim());
}

const hasClaim = computed(() => props.platform?.capabilities.includes("provision.run") ?? false);
const hasHealth = computed(() => props.platform?.capabilities.includes("health.check") ?? false);
</script>

<template>
  <div v-if="account && platform" class="detail">
    <div class="detail-head">
      <PlatformBadge :name="platform.platform_name" :color-index="faceOf(account.account_id)" />
      <span class="detail-id mono">{{ account.account_id }}</span>
      <button class="detail-close" aria-label="收起详情" @click="emit('close')">✕</button>
    </div>

    <p class="detail-status">
      <span class="tag" :class="`tag--${account.signal}`">{{ signalText(account.signal) }}</span>
      <span v-if="earliestExpiry(account)" class="row-sub num">
        凭据最早 {{ fmtTime(earliestExpiry(account)) }} 到期
      </span>
    </p>

    <p class="detail-label">别名</p>
    <div class="alias-row">
      <input
        v-model="aliasDraft"
        class="alias-input"
        type="text"
        maxlength="40"
        :placeholder="account.account_name"
        aria-label="账户别名"
      />
      <button
        class="btn btn--ghost"
        :disabled="busy || !aliasDirty"
        @click="saveAlias"
      >保存</button>
    </div>
    <p class="row-sub alias-hint">
      别名用于对上号（如「Trae 主号」）；留空保存 = 清除，显示回连接器给的名称。账户 id 不变。
    </p>

    <p class="detail-label">凭据</p>
    <ul v-if="account.credentials.length" class="cred-rows">
      <li v-for="cred in account.credentials" :key="cred.kind" class="cred-row">
        <span class="cred-kind">{{ cred.kind }}</span>
        <span class="row-sub">{{ cred.level }}</span>
        <span v-if="cred.expires_at" class="row-sub num cred-exp">
          {{ fmtTime(cred.expires_at) }} 到期
        </span>
        <span v-if="cred.revoked" class="row-sub">本地副本已撤销，等待重新停靠</span>
        <span class="tag" :class="`tag--${cred.signal}`">{{ signalText(cred.signal) }}</span>
      </li>
    </ul>
    <p v-else class="quietline">该账户还没有凭据。</p>

    <p class="detail-label">会话（R5 首批 = 工作区/配置上下文）</p>
    <ul v-if="account.sessions.length" class="cred-rows">
      <li v-for="(s, i) in account.sessions" :key="i" class="cred-row">
        <span class="cred-kind session-loc">{{ sessionLabel(s.location) }}</span>
        <span class="row-sub">{{ s.kind }}</span>
        <span class="row-sub num">{{ s.level }}</span>
      </li>
    </ul>
    <p v-else class="quietline">还没有入库会话——点「扫会话」做一次只读枚举。</p>

    <p v-if="account.evidence.length" class="detail-evidence">
      {{ account.evidence.join("；") }}
    </p>
    <p v-if="account.repair_hint" class="row-fix">建议：{{ account.repair_hint }}</p>

    <span v-if="hasClaim || hasHealth" class="row-actions detail-actions">
      <button
        v-if="hasClaim"
        class="btn btn--primary"
        :disabled="busy"
        @click="emit('claim', platform.id)"
      >领取</button>
      <button
        v-if="hasHealth"
        class="btn"
        :class="hasClaim ? 'btn--ghost' : 'btn--primary'"
        :disabled="busy"
        @click="emit('health', platform.id)"
      >体检</button>
      <button class="btn btn--ghost" :disabled="busy" @click="emit('scanSessions', account.account_id)">
        扫会话
      </button>
    </span>
  </div>
  <p v-else class="detail-empty">在矩阵里点一行账户，看它的凭据与体检详情。</p>
</template>

<style scoped>
.detail-empty { color: var(--color-text-faint); font-size: var(--text-sm); }

/* 别名行：输入 + 保存（ADR-030）；只在有改动时可点，避免误触空提交 */
.alias-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.alias-input {
  flex: 1;
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  font-size: var(--text-sm);
}
.alias-input:focus { outline: 2px solid var(--color-accent-weak); border-color: var(--color-accent); }
.alias-hint { margin: var(--space-2) 0 0; }

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
.session-loc {
  max-width: 40ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-evidence {
  margin: var(--space-3) 0 0;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  line-height: 1.6;
}
.detail-actions { margin-top: var(--space-3); }
</style>
