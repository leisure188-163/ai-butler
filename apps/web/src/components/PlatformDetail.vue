<script setup lang="ts">
/**
 * 平台详情展开块（2026-11-18 从 PlatformsPage 拆出，控在文件行数红线内）。
 * 三段折叠：能力清单 / 平台信息（唯一可编辑段）/ 账户。
 * 编辑只在本地状态，保存时把 patch 交回页面（端不做业务判定）。
 */
import { ref } from "vue";

import type { AccountItem, PlatformItem } from "../types";

const props = defineProps<{
  platform: PlatformItem;
  accounts: AccountItem[];
  busy: boolean;
}>();

const emit = defineEmits<{
  save: [
    patch: { platform_name?: string | null; active?: boolean; times?: string[] | null },
  ];
}>();

const section = ref<"caps" | "profile" | "accts" | null>(null);
const editing = ref(false);
const editName = ref("");
const editActive = ref(true);
const editTimes = ref<string[]>([]);

function toggleSection(name: "caps" | "profile" | "accts"): void {
  section.value = section.value === name ? null : name;
}

function beginEdit(): void {
  editing.value = true;
  editName.value = props.platform.display;
  editActive.value = props.platform.active;
  editTimes.value = [...props.platform.schedule_times];
}

function cancelEdit(): void {
  editing.value = false;
  editName.value = "";
  editTimes.value = [];
}

function addSlot(): void {
  if (editTimes.value.length >= 8) return; // manifest 上限 4，给一倍余量
  editTimes.value.push("09:15");
}

function removeSlot(index: number): void {
  editTimes.value.splice(index, 1);
}

function saveProfile(): void {
  const patch: { platform_name?: string | null; active?: boolean; times?: string[] | null } = {};
  const name = editName.value.trim();
  if (name && name !== props.platform.display) patch.platform_name = name;
  if (editActive.value !== props.platform.active) patch.active = editActive.value;
  const times = [...new Set(editTimes.value.filter(Boolean))].sort();
  if (JSON.stringify(times) !== JSON.stringify(props.platform.schedule_times)) patch.times = times;
  if (Object.keys(patch).length) emit("save", patch);
  cancelEdit();
}

/** 名称恢复 manifest 名（空串语义） */
function resetName(): void {
  emit("save", { platform_name: "" });
  cancelEdit();
}

/** 调度恢复平台默认：times=null 跟随 manifest（空数组则是不排班，两者语义不同） */
function resetSchedule(): void {
  emit("save", { times: null });
  cancelEdit();
}
</script>

<template>
  <div class="detail-fold">
    <button class="fold-head" :aria-expanded="section === 'caps'" @click="toggleSection('caps')">
      <span class="fold-caret">{{ section === 'caps' ? '▾' : '▸' }}</span>
      能力清单
      <span class="fold-hint">{{ platform.capabilities.length }} 项</span>
    </button>
    <p v-if="section === 'caps'" class="fold-body mono">{{ platform.capabilities.join(" · ") || "—" }}</p>

    <button class="fold-head" :aria-expanded="section === 'profile'" @click="toggleSection('profile')">
      <span class="fold-caret">{{ section === 'profile' ? '▾' : '▸' }}</span>
      平台信息
      <span class="fold-hint">
        {{ platform.active ? "启用" : "已停用" }} · {{ platform.schedule_times.join("、") || "未排班" }}
      </span>
    </button>
    <div v-if="section === 'profile'" class="fold-body">
      <template v-if="editing">
        <label class="edit-row">
          <span class="edit-label">平台名称</span>
          <input v-model="editName" class="input edit-name" maxlength="40" :disabled="busy" />
          <button
            v-if="platform.display !== platform.id"
            class="btn btn--ghost"
            :disabled="busy"
            @click="resetName"
          >恢复默认名</button>
        </label>
        <label class="edit-row">
          <span class="edit-label">启用</span>
          <input v-model="editActive" type="checkbox" :disabled="busy" />
          <span class="fold-note">停用后不再定时领取，手动领取仍可</span>
        </label>
        <div class="edit-row">
          <span class="edit-label">调度执行时间</span>
          <div class="sched-edit">
            <span v-for="(_, i) in editTimes" :key="i" class="sched-item">
              <input v-model="editTimes[i]" class="input sched-input mono" type="time" :disabled="busy" />
              <button class="btn btn--ghost" :disabled="busy" @click="removeSlot(i)">删除</button>
            </span>
            <button class="btn btn--ghost" :disabled="busy || editTimes.length >= 8" @click="addSlot">+ 添加时间</button>
          </div>
        </div>
        <p class="fold-note">
          清空时间并保存 = 该平台不再定时领取；{{ platform.schedule_overridden ? "当前调度为自定义" : "当前调度为平台默认" }}
        </p>
        <span v-if="platform.schedule_overridden" class="row-actions">
          <button class="btn btn--ghost" :disabled="busy" @click="resetSchedule">恢复平台默认调度</button>
        </span>
        <span class="row-actions">
          <button class="btn btn--primary" :disabled="busy" @click="saveProfile">保存</button>
          <button class="btn btn--ghost" :disabled="busy" @click="cancelEdit">取消</button>
        </span>
      </template>
      <template v-else>
        <p class="fold-line"><span class="edit-label">显示名</span>{{ platform.display }}</p>
        <p class="fold-line"><span class="edit-label">平台状态</span>{{ platform.active ? "启用" : "已停用" }}</p>
        <p class="fold-line">
          <span class="edit-label">凭据类型</span>{{ platform.credential_kinds.join("、") || "—" }}
        </p>
        <p class="fold-line">
          <span class="edit-label">调度执行时间</span>{{ platform.schedule_times.join("、") || "未排班" }}
          <span v-if="platform.schedule_overridden" class="tag tag--quiet sched-tag">自定义</span>
        </p>
        <p class="fold-note">平台编码、类型、版本、能力、凭据类型来自连接器探测，不可编辑。</p>
        <span class="row-actions">
          <button class="btn btn--ghost" :disabled="busy" @click="beginEdit">修改</button>
        </span>
      </template>
    </div>

    <button class="fold-head" :aria-expanded="section === 'accts'" @click="toggleSection('accts')">
      <span class="fold-caret">{{ section === 'accts' ? '▾' : '▸' }}</span>
      账户（{{ accounts.length }}）
    </button>
    <div v-if="section === 'accts'" class="fold-body">
      <p class="fold-body mono">{{ accounts.map((a) => a.account_id).join("、") || "—" }}</p>
    </div>
  </div>
</template>

<style scoped>
.detail-fold { display: flex; flex-direction: column; gap: var(--space-1); padding: var(--space-2) 0; }
.fold-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) 0;
  background: none;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text);
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
}
.fold-head:hover { color: var(--color-accent); }
.fold-caret { width: 1em; color: var(--color-text-muted); }
.fold-hint { margin-left: auto; color: var(--color-text-muted); font-size: var(--text-xs); }
.fold-body { padding: var(--space-2) 0 var(--space-3); }
.fold-note { color: var(--color-text-muted); font-size: var(--text-xs); }
.fold-value { font-family: var(--font-mono); font-size: var(--text-sm); }

/* 调度执行时间内联编辑（2026-11-18） */
.sched-edit {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.sched-item { display: inline-flex; align-items: center; gap: var(--space-1); }
.sched-input { width: 7.5rem; }
.sched-tag { margin-left: var(--space-1); }

/* 平台信息编辑行（2026-11-18） */
.edit-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0;
}
.edit-label {
  min-width: 7rem;
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}
.edit-name { width: 14rem; }
.fold-line { padding: var(--space-1) 0; font-size: var(--text-sm); }
</style>
