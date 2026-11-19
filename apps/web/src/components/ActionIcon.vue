/**
 * 行操作图标唯一入口（docs/conventions/07-列表设计规范）。
 *
 * 列表行操作不再用文字表白动作名：按钮里只放图标，动作名交给 `title` 与
 * `aria-label`（鼠标停留即可读）。新增动作图标**先在这里登记**，禁止在页面
 * 或组件里内联散装 SVG——否则同一动作在不同列表会长得不一样。
 */
<script setup lang="ts">
defineProps<{ name: "edit" | "refresh" | "dots" | "claim" | "health" | "expand" }>();
</script>

<template>
  <svg
    v-if="name === 'edit'"
    class="act-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    aria-hidden="true"
  >
    <path d="M4 20h4L18.5 9.5a2.12 2.12 0 0 0-3-3L5 16v4" />
    <path d="M13.5 6.5 17.5 10.5" />
  </svg>
  <svg
    v-else-if="name === 'refresh'"
    class="act-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    aria-hidden="true"
  >
    <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
    <path d="M3 3v5h5" />
    <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
    <path d="M16 16h5v5" />
  </svg>
  <svg
    v-else-if="name === 'claim'"
    class="act-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    aria-hidden="true"
  >
    <path d="M12 3v11" />
    <path d="m8 10 4 4 4-4" />
    <path d="M5 20h14" />
  </svg>
  <svg
    v-else-if="name === 'health'"
    class="act-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    aria-hidden="true"
  >
    <path d="M3 12h3.2l2.6-7.2 4.4 14.4 2.6-7.2H21" />
  </svg>
  <svg
    v-else-if="name === 'expand'"
    class="act-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    aria-hidden="true"
  >
    <path d="m6 9 6 6 6-6" />
  </svg>
  <svg
    v-else
    class="act-icon"
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
  >
    <circle cx="5.5" cy="12" r="1.7" />
    <circle cx="12" cy="12" r="1.7" />
    <circle cx="18.5" cy="12" r="1.7" />
  </svg>
</template>

<style scoped>
.act-icon {
  width: 16px;
  height: 16px;
}
</style>
