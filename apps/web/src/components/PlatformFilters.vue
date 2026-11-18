<script setup lang="ts">
/**
 * 平台检索条（2026-11-18）：关键字 + 启用状态 + 平台类型 + 排序。
 * 每个控件独立 v-model 各自字段（不合并成整对象回传）——否则连续改两个控件时，
 * 后一次会用上一帧的旧值把前一次的选择覆盖掉。
 */
import { computed } from "vue";

import type { PlatformQuery } from "../types";

const props = defineProps<{
  keyword: string;
  status: PlatformQuery["status"];
  kind: PlatformQuery["kind"];
  sort: PlatformQuery["sort"];
  total: number;
  matched: number;
}>();

const emit = defineEmits<{
  "update:keyword": [value: string];
  "update:status": [value: PlatformQuery["status"]];
  "update:kind": [value: PlatformQuery["kind"]];
  "update:sort": [value: PlatformQuery["sort"]];
}>();

const dirty = computed(
  () => props.keyword.trim() !== "" || props.status !== "all" || props.kind !== "all",
);

function reset(): void {
  emit("update:keyword", "");
  emit("update:status", "all");
  emit("update:kind", "all");
  emit("update:sort", "code");
}
</script>

<template>
  <div class="filters">
    <input
      class="input filters__search"
      type="search"
      placeholder="搜索平台编码 / 名称"
      :value="keyword"
      @input="emit('update:keyword', ($event.target as HTMLInputElement).value)"
    />
    <select
      class="input filters__select"
      :value="status"
      @change="emit('update:status', ($event.target as HTMLSelectElement).value as PlatformQuery['status'])"
    >
      <option value="all">全部状态</option>
      <option value="active">仅启用</option>
      <option value="inactive">仅停用</option>
    </select>
    <select
      class="input filters__select"
      :value="kind"
      @change="emit('update:kind', ($event.target as HTMLSelectElement).value as PlatformQuery['kind'])"
    >
      <option value="all">全部类型</option>
      <option value="web">网页版</option>
      <option value="client">客户端</option>
    </select>
    <select
      class="input filters__select"
      :value="sort"
      @change="emit('update:sort', ($event.target as HTMLSelectElement).value as PlatformQuery['sort'])"
    >
      <option value="code">按平台编码</option>
      <option value="name">按平台名称</option>
      <option value="accounts">按账户数</option>
    </select>
    <span class="filters__count">
      {{ matched }} / {{ total }} 个平台
    </span>
    <button v-if="dirty" class="btn btn--ghost" @click="reset">清除筛选</button>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.filters__search { flex: 1 1 12rem; min-width: 8rem; }
.filters__select { flex: 0 0 auto; }
.filters__count { color: var(--color-text-muted); font-size: var(--text-sm); }
</style>
