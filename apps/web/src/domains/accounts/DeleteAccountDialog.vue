<script setup lang="ts">
/**
 * 删除账户确认（2026-11-19 用户裁决）：账户行与关联凭据一并删除，不留脏数据。
 * 凭据条数直接取契约 `AccountOut.credentials`（端不猜、不自己查库）。
 */
import { computed } from "vue";

import ModalShell from "@/shared/components/ModalShell.vue";
import type { AccountItem } from "@/shared/types";

const props = defineProps<{
  account: AccountItem;
  busy: boolean;
}>();

const emit = defineEmits<{ close: []; confirm: [] }>();

const credentialCount = computed(() => props.account.credentials.length);
const displayName = computed(
  () => props.account.alias || props.account.account_name || props.account.account_id,
);
</script>

<template>
  <ModalShell
    title="删除账户？"
    :subtitle="`${displayName}（${props.account.account_id}）`"
    :busy="props.busy"
    @close="emit('close')"
  >
    <p v-if="credentialCount" class="delete-copy">
      该账户还有 <strong>{{ credentialCount }}</strong> 条关联凭据，将一并删除；删除后需重新导入本机客户端才能恢复。
    </p>
    <p v-else class="delete-copy">
      该账户没有关联凭据；删除后需重新导入本机客户端才能恢复。
    </p>
    <template #footer>
      <button class="btn" :disabled="props.busy" @click="emit('close')">取消</button>
      <button class="btn btn--danger" :disabled="props.busy" @click="emit('confirm')">
        删除账户
      </button>
    </template>
  </ModalShell>
</template>

<style scoped>
.delete-copy {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  line-height: 1.7;
}
.delete-copy strong { color: var(--color-danger-ink); }
</style>
