<script setup lang="ts">
/**
 * 新建接入源弹层（ADR-033）：relay / local / api 型上游，不依赖本机客户端连接器。
 *
 * 只收表单直传契约；编码形状、URL/协议词表、base_url 必填由 core 判定。
 */
import { computed, ref } from "vue";
import ModalShell from "@/shared/components/ModalShell.vue";
import type { ProviderDraft } from "@/domains/platforms/types";

const props = defineProps<{ busy: boolean }>();
const emit = defineEmits<{
  close: [];
  submit: [draft: ProviderDraft];
}>();

const code = ref("");
const name = ref("");
const kind = ref("relay");
const baseUrl = ref("");
const protocol = ref("openai");
const models = ref("");
const credentialKinds = ref("api_key");

const canSubmit = computed(
  () =>
    !props.busy &&
    code.value.trim() !== "" &&
    name.value.trim() !== "" &&
    baseUrl.value.trim() !== "" &&
    protocol.value.trim() !== "",
);

function splitList(raw: string): string[] {
  return raw.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean);
}

function submit(): void {
  if (!canSubmit.value) return;
  emit("submit", {
    platform_code: code.value.trim().toLowerCase(),
    platform_name: name.value.trim(),
    kind: kind.value,
    base_url: baseUrl.value.trim(),
    protocol: protocol.value,
    models: splitList(models.value),
    credential_kinds: splitList(credentialKinds.value),
  });
}
</script>

<template>
  <ModalShell
    title="新建接入源"
    subtitle="中转站 / 本地模型 / 官方 API：填地址与协议即可，账号与密钥在账户页绑定。"
    :busy="busy"
    @close="emit('close')"
  >
    <form id="provider-create-form" class="form-grid" @submit.prevent="submit">
      <label class="field">
        <span class="field__label">接入源编码</span>
        <input v-model="code" class="input mono" type="text" placeholder="如 my_relay（创建后冻结）" />
      </label>
      <label class="field">
        <span class="field__label">显示名</span>
        <input v-model="name" class="input" type="text" maxlength="40" placeholder="如「公司中转站」" />
      </label>
      <label class="field">
        <span class="field__label">类型</span>
        <select v-model="kind" class="input">
          <option value="relay">中转（OpenAI 兼容）</option>
          <option value="local">本地模型</option>
          <option value="api">官方 API</option>
        </select>
      </label>
      <label class="field">
        <span class="field__label">上游协议</span>
        <select v-model="protocol" class="input">
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="gemini">Gemini（互译未开工，暂不可转发）</option>
        </select>
      </label>
      <label class="field field--wide">
        <span class="field__label">Base URL</span>
        <input v-model="baseUrl" class="input mono" type="url" placeholder="https://api.example.com/v1" />
      </label>
      <label class="field field--wide">
        <span class="field__label">模型列表（可选，逗号分隔）</span>
        <input v-model="models" class="input mono" type="text" placeholder="gpt-4o-mini, text-embedding-3-small" />
      </label>
      <label class="field field--wide">
        <span class="field__label">凭据类型（可选，逗号分隔）</span>
        <input v-model="credentialKinds" class="input mono" type="text" placeholder="api_key" />
      </label>
    </form>
    <template #footer>
      <span class="field__note">接入源不排班、不产生客户端动作；账号健康由密钥可用性决定。</span>
      <div class="foot-actions">
        <button class="btn btn--ghost" type="button" :disabled="busy" @click="emit('close')">取消</button>
        <button class="btn btn--primary" type="submit" form="provider-create-form" :disabled="!canSubmit">
          创建接入源
        </button>
      </div>
    </template>
  </ModalShell>
</template>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}
.field { display: grid; gap: var(--space-1); min-width: 0; }
.field--wide { grid-column: 1 / -1; }
.field__label { font-size: var(--text-xs); color: var(--color-text-muted); }
.field__note { margin: 0; font-size: var(--text-xs); color: var(--color-text-faint); }
.foot-actions { display: flex; gap: var(--space-2); }
@media (max-width: 640px) {
  .form-grid { grid-template-columns: 1fr; }
}
</style>
