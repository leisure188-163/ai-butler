<script setup lang="ts">
/**
 * 手建账户弹层（ADR-035）：API 型接入源、连接器没扫到的小号都从这里进。
 *
 * 只收表单并直传契约（AccountCreateIn）；人工后缀可空、平台存在性、凭据槽位形状
 * 全由 server/core 判定，端不做业务校验（红线 2）。
 */
import { computed, ref, watch } from "vue";
import ModalShell from "@/shared/components/ModalShell.vue";
import type { AccountCreatePayload } from "@/domains/accounts/api";
import type { PlatformItem } from "@/shared/types";

const props = defineProps<{
  platforms: PlatformItem[];
  busy: boolean;
}>();

const emit = defineEmits<{
  close: [];
  submit: [payload: AccountCreatePayload];
}>();

const platformCode = ref(props.platforms[0]?.id ?? "");
const name = ref("");
const alias = ref("");
const code = ref("");
const baseUrl = ref(props.platforms[0]?.base_url ?? "");
const nickname = ref("");
const email = ref("");
const kind = ref(props.platforms[0]?.credential_kinds?.[0] ?? "api_key");
const secret = ref("");
const slot = ref("default");
const label = ref("");

const selected = computed(() => props.platforms.find((p) => p.id === platformCode.value) ?? null);
watch(selected, (platform) => {
  if (!platform) return;
  baseUrl.value = platform.base_url ?? "";
  kind.value = platform.credential_kinds?.[0] ?? "api_key";
}, { immediate: true });

const canSubmit = computed(
  () => !props.busy && platformCode.value.trim() !== "" && name.value.trim() !== "",
);

function submit(): void {
  if (!canSubmit.value) return;
  emit("submit", {
    platform_code: platformCode.value,
    account_code: code.value.trim() || undefined,
    account_name: name.value.trim(),
    alias: alias.value.trim(),
    base_url: baseUrl.value.trim(),
    identity: {
      nickname: nickname.value.trim(),
      email: email.value.trim(),
    },
    kind: kind.value.trim() || undefined,
    secret: secret.value || undefined,
    slot: slot.value.trim() || "default",
    label: label.value.trim(),
  });
}
</script>

<template>
  <ModalShell
    title="新建账户"
    subtitle="账户名只显示账户本身；后缀可留空，等关联登录账户时再填。"
    :busy="busy"
    @close="emit('close')"
  >
    <form id="account-create-form" class="form-grid" @submit.prevent="submit">
      <label class="field">
        <span class="field__label">平台 / 接入源</span>
        <select v-model="platformCode" class="input">
          <option v-for="p in platforms" :key="p.id" :value="p.id">
            {{ p.platform_name }}（{{ p.id }}）
          </option>
        </select>
      </label>
      <label class="field">
        <span class="field__label">显示名</span>
        <input v-model="name" class="input" type="text" maxlength="60" placeholder="如「主力账号」" />
      </label>
      <label class="field">
        <span class="field__label">别名（可选）</span>
        <input v-model="alias" class="input" type="text" maxlength="40" placeholder="盖掉连接器泛名" />
      </label>
      <label class="field">
        <span class="field__label">账户后缀（人工，可选）</span>
        <input v-model="code" class="input mono" type="text" placeholder="留空 = 尚未关联登录账户" />
      </label>
      <label class="field field--wide">
        <span class="field__label">账户级接入地址（可选）</span>
        <input v-model="baseUrl" class="input mono" type="text" placeholder="留空 = 用接入源默认地址" />
      </label>
      <label class="field">
        <span class="field__label">真实昵称（可选）</span>
        <input v-model="nickname" class="input" type="text" placeholder="连接器取不到时手填" />
      </label>
      <label class="field">
        <span class="field__label">邮箱（可选）</span>
        <input v-model="email" class="input" type="email" placeholder="用于对上真实身份" />
      </label>

      <p class="field__note field--wide">
        首份密钥（可选）：写入保险库，明文不回显；之后可在账户详情追加/撤销槽位。
      </p>
      <label class="field">
        <span class="field__label">凭据类型</span>
        <input v-model="kind" class="input mono" type="text" placeholder="api_key" />
      </label>
      <label class="field">
        <span class="field__label">槽位</span>
        <input v-model="slot" class="input mono" type="text" placeholder="default" />
      </label>
      <label class="field field--wide">
        <span class="field__label">密钥</span>
        <input v-model="secret" class="input mono" type="password" autocomplete="off" placeholder="粘贴 API key" />
      </label>
      <label class="field field--wide">
        <span class="field__label">密钥显示名（可选）</span>
        <input v-model="label" class="input" type="text" maxlength="40" placeholder="主 key / 备用 key" />
      </label>
    </form>
    <template #footer>
      <span class="field__note">平台不存在时先到平台页创建接入源。</span>
      <div class="foot-actions">
        <button class="btn btn--ghost" type="button" :disabled="busy" @click="emit('close')">取消</button>
        <button class="btn btn--primary" type="submit" form="account-create-form" :disabled="!canSubmit">
          创建账户
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
