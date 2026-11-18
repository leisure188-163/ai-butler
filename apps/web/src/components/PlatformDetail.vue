<script setup lang="ts">
/**
 * 平台详情弹层（2026-11-19）：点击列表里的平台名打开，不再往表格里塞展开行。
 * 只读展示契约字段；修改入口由行内「修改」与本弹层底部按钮显式提供。
 */
import ModalShell from "./ModalShell.vue";
import type { AccountItem, PlatformItem } from "../types";

defineProps<{
  platform: PlatformItem;
  accounts: AccountItem[];
  busy?: boolean;
}>();

const emit = defineEmits<{ close: []; edit: [] }>();
</script>

<template>
  <ModalShell
    :title="`平台详情 · ${platform.display}`"
    :busy="busy"
    @close="emit('close')"
  >
    <section class="pd-sec">
      <div class="pd-grid">
        <div><span class="pd-key">平台编码</span><code class="mono">{{ platform.id }}</code></div>
        <div><span class="pd-key">状态</span>{{ platform.active ? "启用" : "已停用" }}</div>
        <div><span class="pd-key">类型</span>{{ platform.kind || "—" }}</div>
        <div>
          <span class="pd-key">客户端版本</span>
          {{ platform.client_version ? `v${platform.client_version}` : "—" }}
        </div>
      </div>
    </section>

    <section class="pd-sec">
      <h3 class="pd-title">调度执行时间</h3>
      <p class="pd-text">
        {{ platform.schedule_times.join("、") || "未排班" }}
        <span v-if="platform.schedule_overridden" class="tag tag--quiet">自定义</span>
      </p>
    </section>

    <section class="pd-sec">
      <h3 class="pd-title">能力清单 · {{ platform.capabilities.length }} 项</h3>
      <p class="pd-text mono">{{ platform.capabilities.join(" · ") || "—" }}</p>
      <p class="pd-hint">凭据类型：{{ platform.credential_kinds.join("、") || "—" }}</p>
    </section>

    <section class="pd-sec">
      <h3 class="pd-title">关联账户 · {{ accounts.length }}</h3>
      <ul v-if="accounts.length" class="pd-accounts">
        <li v-for="account in accounts" :key="account.account_id">
          <span class="pd-account-name">{{ account.account_name }}</span>
          <code class="mono pd-account-id">{{ account.account_id }}</code>
        </li>
      </ul>
      <p v-else class="pd-text">—</p>
    </section>

    <template #footer>
      <span class="pd-actions">
        <button class="btn btn--ghost" :disabled="busy" @click="emit('close')">关闭</button>
        <button class="btn btn--primary" :disabled="busy" @click="emit('edit')">修改平台信息</button>
      </span>
    </template>
  </ModalShell>
</template>

<style scoped>
.pd-sec {
  padding: 14px 0;
  border-top: 1px solid var(--color-border);
}
.pd-sec:first-child {
  padding-top: 0;
  border-top: 0;
}
.pd-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 18px;
}
.pd-grid > div {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
  font-size: var(--text-sm);
}
.pd-key {
  flex: 0 0 76px;
  color: var(--color-text-faint);
  font-size: var(--text-xs);
}
.pd-title {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}
.pd-text {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--color-text);
}
.pd-hint {
  margin: 6px 0 0;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--color-text-faint);
}
.pd-accounts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.pd-accounts li {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: var(--text-sm);
}
.pd-account-name {
  font-weight: 500;
}
.pd-account-id {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}
.pd-actions {
  display: inline-flex;
  gap: var(--space-2);
  margin-left: auto;
}
@media (max-width: 640px) {
  .pd-grid {
    grid-template-columns: 1fr;
  }
  .pd-actions {
    width: 100%;
  }
  .pd-actions :deep(.btn) {
    flex: 1;
  }
}
</style>
