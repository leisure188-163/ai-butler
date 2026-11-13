<script setup lang="ts">
/**
 * 应用小徽（ADR-009 矩阵改版）：身份色点 + 应用名——身份色唯一合法载体。
 * 色值取 --card-face-1..6 单值（跨主题一致）；散列由调用方用 faceOf 预先算好传入，
 * 本组件不做散列、不做卡片化装饰。
 */
withDefaults(
  defineProps<{
    name: string;
    /** 身份色序号 1..6（调用方经 faceOf(account_id) 算出） */
    colorIndex: number;
    size?: "sm" | "md";
  }>(),
  { size: "md" },
);
</script>

<template>
  <span class="badge" :class="`badge--${size}`">
    <span
      class="badge-dot"
      :style="{ background: `var(--card-face-${colorIndex})` }"
      aria-hidden="true"
    ></span>
    <span class="badge-name">{{ name }}</span>
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.badge--md .badge-name { font-size: var(--text-sm); }
.badge--sm .badge-name { font-size: var(--text-xs); }
.badge-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
