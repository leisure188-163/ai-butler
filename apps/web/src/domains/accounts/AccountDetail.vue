<script setup lang="ts">
/**
 * 账户详情面板（六页 IA，ADR-010）：矩阵行下展开的体检明细。
 * 保留凭据清单/证据/repair_hint/能力驱动按钮。
 * 动作按钮按能力矩阵渲染（AppOut.capabilities，端零映射）：
 * provision.run = 领取；health.check = 体检（R3 网页通道）。
 */
import { computed, ref, watch } from "vue";
import type { AccountItem, PlatformItem } from "@/shared/types";
import type { AccountPatch } from "@/domains/accounts/api";
import { earliestExpiry, faceOf, fmtTime, signalText } from "@/shared/utils/format";
import PlatformBadge from "@/domains/platforms/PlatformBadge.vue";

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
  update: [accountId: string, patch: AccountPatch];
  addKey: [accountId: string, key: { kind: string; secret: string; slot: string; label: string }];
  revokeKey: [accountId: string, kind: string, slot: string];
  close: [];
}>();

/* 别名草稿跟随当前账户；账户换人时重置，避免把上一张卡的输入带到下一张 */
const aliasDraft = ref("");
const baseUrlDraft = ref("");
watch(
  () => props.account?.account_id,
  () => {
    aliasDraft.value = props.account?.alias ?? "";
    baseUrlDraft.value = props.account?.base_url ?? "";
    keyFormOpen.value = false;
    keySecret.value = "";
  },
  { immediate: true },
);
const aliasDirty = computed(
  () => aliasDraft.value.trim() !== (props.account?.alias ?? ""),
);
const baseUrlDirty = computed(
  () => baseUrlDraft.value.trim() !== (props.account?.base_url ?? ""),
);

function saveAlias() {
  if (!props.account) return;
  emit("rename", props.account.account_id, aliasDraft.value.trim());
}

function saveBaseUrl() {
  if (!props.account) return;
  emit("update", props.account.account_id, { base_url: baseUrlDraft.value.trim() });
}

function toggleActive() {
  if (!props.account) return;
  emit("update", props.account.account_id, { active: !props.account.active });
}

/* 密钥槽位（ADR-033）：API 型账户可多 key；连接器账户的凭据由客户端停靠写入 */
const keyFormOpen = ref(false);
const keyKind = ref("");
const keySecret = ref("");
const keySlot = ref("default");
const keyLabel = ref("");
const canManageKeys = computed(
  () => props.account?.origin === "manual" || props.platform?.origin === "user",
);

function openKeyForm() {
  keyFormOpen.value = true;
  keyKind.value = props.platform?.credential_kinds?.[0] ?? "api_key";
  keySlot.value = props.account?.credentials.length ? "key2" : "default";
  keySecret.value = "";
  keyLabel.value = "";
}

function submitKey() {
  if (!props.account || !keyKind.value.trim() || !keySecret.value) return;
  emit("addKey", props.account.account_id, {
    kind: keyKind.value.trim(),
    secret: keySecret.value,
    slot: keySlot.value.trim() || "default",
    label: keyLabel.value.trim(),
  });
  keyFormOpen.value = false;
  keySecret.value = "";
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
      <span class="row-sub">
        {{ account.origin === "manual" ? "手建账户" : "连接器导入" }}
      </span>
      <button class="btn btn--ghost btn--tiny" :disabled="busy" @click="toggleActive">
        {{ account.active ? "停用" : "启用" }}
      </button>
    </p>
    <p v-if="account.identity.email || account.identity.uid || account.identity.source_key" class="row-sub detail-identity">
      <span v-if="account.identity.email">{{ account.identity.email }}</span>
      <span v-if="account.identity.uid">uid {{ account.identity.uid }}</span>
      <span v-if="account.identity.source_key" class="mono">key {{ account.identity.source_key }}</span>
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
      别名用于对上号（如「Trae 主号」）；留空保存 = 清除，显示回 core 计算的标签。账户 id 不变。
    </p>

    <template v-if="platform.origin === 'user'">
      <p class="detail-label">接入地址</p>
      <div class="alias-row">
        <input
          v-model="baseUrlDraft"
          class="alias-input mono"
          type="text"
          :placeholder="platform.base_url"
          aria-label="账户接入地址"
        />
        <button class="btn btn--ghost" :disabled="busy || !baseUrlDirty" @click="saveBaseUrl">
          保存
        </button>
      </div>
      <p class="row-sub alias-hint">
        留空 = 使用接入源默认地址（{{ platform.base_url }}）；账户级地址只覆盖本账户。
      </p>
    </template>

    <div class="cred-head">
      <p class="detail-label">凭据</p>
      <button
        v-if="canManageKeys && !keyFormOpen"
        class="btn btn--ghost btn--tiny"
        :disabled="busy"
        @click="openKeyForm"
      >添加密钥</button>
    </div>
    <ul v-if="account.credentials.length" class="cred-rows">
      <li
        v-for="cred in account.credentials"
        :key="`${cred.kind}:${cred.slot}`"
        class="cred-row"
      >
        <span class="cred-kind">{{ cred.kind }}</span>
        <span class="slot-tag mono">{{ cred.label || cred.slot }}</span>
        <span class="row-sub">{{ cred.level }}</span>
        <span v-if="cred.expires_at" class="row-sub num cred-exp">
          {{ fmtTime(cred.expires_at) }} 到期
        </span>
        <span v-if="cred.revoked" class="row-sub">本地副本已撤销，等待重新停靠</span>
        <span class="tag" :class="`tag--${cred.signal}`">{{ signalText(cred.signal) }}</span>
        <button
          v-if="canManageKeys && !cred.revoked"
          class="cred-remove"
          :disabled="busy"
          :aria-label="`撤销 ${cred.kind} ${cred.slot}`"
          @click="emit('revokeKey', account.account_id, cred.kind, cred.slot)"
        >撤销</button>
      </li>
    </ul>
    <p v-else class="quietline">该账户还没有凭据。</p>

    <form v-if="keyFormOpen" class="key-form" @submit.prevent="submitKey">
      <div class="key-form__row">
        <label class="key-form__field">
          <span class="row-sub">类型</span>
          <input v-model="keyKind" class="alias-input mono" type="text" placeholder="api_key" />
        </label>
        <label class="key-form__field">
          <span class="row-sub">槽位</span>
          <input v-model="keySlot" class="alias-input mono" type="text" placeholder="default" />
        </label>
      </div>
      <label class="key-form__field">
        <span class="row-sub">密钥</span>
        <input
          v-model="keySecret"
          class="alias-input mono"
          type="password"
          autocomplete="off"
          placeholder="粘贴 API key（只入保险库，不回显）"
        />
      </label>
      <label class="key-form__field">
        <span class="row-sub">显示名（可选）</span>
        <input v-model="keyLabel" class="alias-input" type="text" maxlength="40" placeholder="主 key" />
      </label>
      <div class="key-form__actions">
        <button class="btn btn--primary" type="submit" :disabled="busy || !keyKind.trim() || !keySecret">
          写入保险库
        </button>
        <button class="btn btn--ghost" type="button" @click="keyFormOpen = false">取消</button>
      </div>
    </form>

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

.detail-identity {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin: var(--space-2) 0 0;
}
.btn--tiny { padding: 2px var(--space-2); font-size: var(--text-xs); }

.cred-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.cred-head .detail-label { margin-bottom: var(--space-2); }
.slot-tag {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--color-surface-2);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}
.cred-remove {
  flex: none;
  align-self: center;
  appearance: none;
  border: none;
  background: none;
  color: var(--color-text-faint);
  font-size: var(--text-xs);
  cursor: pointer;
  padding: 0;
}
.cred-remove:hover { color: var(--color-danger, #c0392b); }

.key-form {
  margin-top: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-2);
  display: grid;
  gap: var(--space-2);
}
.key-form__row { display: flex; gap: var(--space-2); }
.key-form__field { display: grid; gap: 2px; flex: 1; min-width: 0; }
.key-form__actions { display: flex; gap: var(--space-2); }

.detail-evidence {
  margin: var(--space-3) 0 0;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  line-height: 1.6;
}
.detail-actions { margin-top: var(--space-3); }
</style>
