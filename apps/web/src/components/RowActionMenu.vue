<script setup lang="ts">
/**
 * 行操作列（2026-11-18）：直连按钮最多 2 个，其余收进「更多」下拉。
 *
 * 为什么不用 inner dropdown：表格容器带 `overflow-x: auto`，行内 absolute 浮层会被
 * 裁掉且会撑出横向滚动条。所以菜单走 Teleport + fixed 定位，用按钮的
 * getBoundingClientRect 定位、右对齐按钮右缘，下方空间不足时向上弹。
 */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { RowAction } from "../types";

const props = defineProps<{
  inline: RowAction[];
  more: RowAction[];
  busy?: boolean;
}>();

const emit = defineEmits<{ run: [key: string] }>();

const open = ref(false);
const anchor = ref<HTMLElement | null>(null);
const menu = ref<HTMLElement | null>(null);
const pos = ref({ top: 0, right: 0 });
const flipped = ref(false);

const ITEM_H = 34;
const PAD = 10;

function place(): void {
  const el = anchor.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const menuH = props.more.length * ITEM_H + PAD;
  const below = window.innerHeight - r.bottom;
  flipped.value = below < menuH + 8 && r.top > menuH + 8;
  pos.value = {
    top: flipped.value ? r.top - menuH - 4 : r.bottom + 4,
    right: window.innerWidth - r.right,
  };
}

function toggle(): void {
  if (props.busy) return;
  open.value = !open.value;
  if (open.value) place();
}

function run(action: RowAction): void {
  if (props.busy || action.disabled) return;
  open.value = false;
  emit("run", action.key);
}

function onDocPointerDown(event: PointerEvent): void {
  if (!open.value) return;
  const target = event.target as Node | null;
  if (menu.value?.contains(target) || anchor.value?.contains(target)) return;
  open.value = false;
}

function onViewportChange(): void {
  if (open.value) open.value = false;
}

onMounted(() => {
  document.addEventListener("pointerdown", onDocPointerDown);
  window.addEventListener("resize", onViewportChange);
  window.addEventListener("scroll", onViewportChange, true);
});

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocPointerDown);
  window.removeEventListener("resize", onViewportChange);
  window.removeEventListener("scroll", onViewportChange, true);
});

/* 行数据变化（上下页/刷新）时菜单不该停留在旧行上 */
watch(
  () => props.more.map((a) => a.label).join("|"),
  () => {
    open.value = false;
  },
);
</script>

<template>
  <span class="row-actions">
    <button
      v-for="action in props.inline"
      :key="action.key"
      class="btn btn--ghost"
      :disabled="props.busy || action.disabled"
      @click.stop="run(action)"
    >{{ action.label }}</button>

    <span v-if="props.more.length" ref="anchor" class="more-anchor">
      <button
        class="btn btn--ghost more-toggle"
        :aria-expanded="open"
        :disabled="props.busy"
        @click.stop="toggle"
      >更多 <span class="caret" :class="{ 'caret--up': open }">▾</span></button>
    </span>
  </span>

  <Teleport to="body">
    <div
      v-if="open"
      ref="menu"
      class="more-menu"
      :class="{ 'more-menu--up': flipped }"
      :style="{ top: `${pos.top}px`, right: `${pos.right}px` }"
      role="menu"
      @click.stop
    >
      <button
        v-for="action in props.more"
        :key="action.key"
        class="more-item"
        :class="{ 'more-item--danger': action.danger }"
        role="menuitem"
        :disabled="props.busy || action.disabled"
        @click="run(action)"
      >{{ action.label }}</button>
    </div>
  </Teleport>
</template>

<style scoped>
.row-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  white-space: nowrap;
}
.more-anchor {
  display: inline-flex;
}
.more-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.caret {
  font-size: 10px;
  color: var(--color-text-muted);
  transition: transform 0.12s ease;
}
.caret--up {
  transform: rotate(180deg);
}
.more-menu {
  position: fixed;
  z-index: 30;
  min-width: 128px;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-card);
}
.more-item {
  padding: 6px 10px;
  background: none;
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.more-item:hover:not(:disabled) {
  background: var(--color-surface-2);
}
.more-item:disabled {
  color: var(--color-text-muted);
  cursor: not-allowed;
}
.more-item--danger {
  color: var(--color-danger);
}
</style>
