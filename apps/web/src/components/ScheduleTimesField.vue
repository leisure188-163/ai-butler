<script setup lang="ts">
/**
 * 调度执行时间编辑控件（2026-11-19）：创建平台与修改平台共用同一份交互。
 * 只维护 HH:MM 字符串数组，不判定业务可否排班；保存与默认值语义由调用方交给契约。
 */
import { computed } from "vue";

const props = defineProps<{
  modelValue: string[];
  busy?: boolean;
  max?: number;
}>();

const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();

const limit = computed(() => props.max ?? 8);

function commit(next: string[]): void {
  emit("update:modelValue", next);
}

function updateAt(index: number, value: string): void {
  const next = [...props.modelValue];
  next[index] = value;
  commit(next);
}

function addSlot(): void {
  if (props.modelValue.length >= limit.value) return;
  commit([...props.modelValue, "09:15"]);
}

function removeSlot(index: number): void {
  commit(props.modelValue.filter((_, i) => i !== index));
}

function clearSlots(): void {
  commit([]);
}
</script>

<template>
  <div class="stf">
    <div v-if="modelValue.length" class="stf-list">
      <span v-for="(time, index) in modelValue" :key="index" class="stf-item">
        <input
          :value="time"
          class="input mono stf-input"
          type="time"
          :disabled="busy"
          :aria-label="`第 ${index + 1} 个执行时间`"
          @input="updateAt(index, ($event.target as HTMLInputElement).value)"
        />
        <button
          type="button"
          class="btn btn--ghost"
          :disabled="busy"
          @click="removeSlot(index)"
        >删除</button>
      </span>
    </div>
    <p v-else class="stf-empty">未设置</p>
    <div class="stf-actions">
      <button
        type="button"
        class="btn btn--ghost"
        :disabled="busy || modelValue.length >= limit"
        @click="addSlot"
      >＋ 添加时间</button>
      <button
        v-if="modelValue.length"
        type="button"
        class="btn btn--ghost"
        :disabled="busy"
        @click="clearSlots"
      >清空</button>
    </div>
  </div>
</template>

<style scoped>
.stf {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 100%;
}
.stf-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.stf-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}
.stf-input {
  width: 8rem;
}
.stf-empty {
  margin: 0;
  color: var(--color-text-faint);
  font-size: var(--text-xs);
}
.stf-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
</style>
