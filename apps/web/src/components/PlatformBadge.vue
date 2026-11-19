<script setup lang="ts">
/**
 * 平台小徽（六页 IA，ADR-010）：身份图标 + 平台名——身份标识唯一合法载体。
 *
 * 有官方图标（`utils/platformIcons` 登记过的平台）时渲染 20px 方形图标；
 * 没登记的回落身份色点（色值取 --card-face-1..6，跨主题一致）。散列由调用方
 * 用 faceOf 预先算好传入，本组件不做散列、不做卡片化装饰。
 */
withDefaults(
  defineProps<{
    name: string;
    /** 身份色序号 1..6（调用方经 faceOf(account_id) 算出） */
    colorIndex: number;
    /** 平台官方图标（本地资源 URL）；缺省 = 用色点 */
    icon?: string | null;
    size?: "sm" | "md";
  }>(),
  { icon: null, size: "md" },
);
</script>

<template>
  <span class="badge" :class="`badge--${size}`">
    <img v-if="icon" class="badge-logo" :src="icon" alt="" aria-hidden="true" />
    <span
      v-else
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
.badge--md .badge-logo { width: 20px; height: 20px; }
.badge--sm .badge-logo { width: 16px; height: 16px; }
.badge-logo {
  flex: none;
  object-fit: contain;
  border-radius: var(--radius-chip);
}
.badge-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
