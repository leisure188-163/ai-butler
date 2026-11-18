<script setup lang="ts">
/**
 * 平台页（ADR-010 六页 IA）：本机接入的各家 AI 助手名册。
 * 六列表 + 虚线邀请行 + 行展开；数据全部来自契约既有 AppOut/AccountOut，
 * 零新端点、零语义加工（能力标签只做协议 kind 的直译，signal 只消费分类）。
 */
import { computed, ref, watch } from "vue";
import PlatformBadge from "../components/PlatformBadge.vue";
import type { AccountItem, PlatformItem, PageName, Signal } from "../types";
import { faceOf, signalText } from "../utils";

const props = defineProps<{
  platforms: PlatformItem[];
  accounts: AccountItem[];
  busyTarget: string | null;
  msg: { text: string; tone: "ok" | "warn" } | null;
  loading: boolean;
  loadError: string;
}>();

const emit = defineEmits<{
  import: [target: string];
  importAll: [];
  savePlatform: [
    target: string,
    patch: { platform_name?: string | null; active?: boolean; times?: string[] | null },
  ];
  jump: [page: PageName];
}>();

/* ---- 平台信息编辑（2026-11-18）：显示名 / 启用状态 / 调度执行时间三合一 ---- */
const editingId = ref<string | null>(null);
const editName = ref("");
const editActive = ref(true);
const editTimes = ref<string[]>([]);

function beginEdit(platform: PlatformItem): void {
  editingId.value = platform.id;
  editName.value = platform.display;
  editActive.value = platform.active;
  editTimes.value = [...platform.schedule_times];
}

function cancelEdit(): void {
  editingId.value = null;
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

function saveProfile(platform: PlatformItem): void {
  const patch: {
    platform_name?: string | null;
    active?: boolean;
    times?: string[] | null;
  } = {};
  const name = editName.value.trim();
  if (name && name !== platform.display) patch.platform_name = name;
  if (editActive.value !== platform.active) patch.active = editActive.value;
  const times = [...new Set(editTimes.value.filter(Boolean))].sort();
  if (JSON.stringify(times) !== JSON.stringify(platform.schedule_times)) patch.times = times;
  if (Object.keys(patch).length) emit("savePlatform", platform.id, patch);
  cancelEdit();
}

/** 名称恢复 manifest 名（空串语义） */
function resetName(platform: PlatformItem): void {
  emit("savePlatform", platform.id, { platform_name: "" });
  cancelEdit();
}

/** 启停一键切换（列表操作列） */
function toggleActive(platform: PlatformItem): void {
  emit("savePlatform", platform.id, { active: !platform.active });
}


const emptyPlatforms = computed(() => props.platforms.filter((a) => !a.account_id));
const importableCount = computed(() => emptyPlatforms.value.length);

function capabilityText(kind: string): string {
  if (kind === "provision.run") return "领取";
  if (kind === "health.check") return "体检";
  if (kind.startsWith("usage")) return "用量";
  return kind;
}

/** 平台类型直译（词表 = core PLATFORM_KINDS；空=未申报） */
function kindText(kind: string): string {
  if (kind === "web") return "网页版";
  if (kind === "client") return "客户端";
  return "—";
}

function accountCount(platform: PlatformItem): number {
  if (platform.account_ids?.length) return platform.account_ids.length;
  return platform.account_id ? 1 : 0;
}

function accountsOf(platform: PlatformItem): AccountItem[] {
  const ids = new Set(platform.account_ids ?? (platform.account_id ? [platform.account_id] : []));
  return props.accounts.filter((a) => ids.has(a.account_id) || a.platform_code === platform.id);
}

const signals: Signal[] = ["ok", "notice", "attention", "danger", "quiet"];

function statusGroups(platform: PlatformItem) {
  const list = accountsOf(platform);
  return signals
    .map((signal) => ({ signal, count: list.filter((a) => a.signal === signal).length }))
    .filter((g) => g.count > 0);
}

/* 分页（2026-11-18）：每页 10 条——接入平台变多后一屏放不下 */
const PAGE_SIZE = 10;
const page = ref(1);

const totalPages = computed(() => Math.max(1, Math.ceil(props.platforms.length / PAGE_SIZE)));

const pagedPlatforms = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE;
  return props.platforms.slice(start, start + PAGE_SIZE);
});

/* 数据刷新/平台增减：页码收敛到合法区间（不跳页、不空页） */
watch(
  () => props.platforms.length,
  () => {
    if (page.value > totalPages.value) page.value = totalPages.value;
  },
);

function goPage(next: number) {
  page.value = Math.min(Math.max(1, next), totalPages.value);
}

const expandedId = ref<string | null>(null);
/** 详情内折叠小节（一次只开一节；默认全收起，点标题展开） */
const section = ref<"caps" | "profile" | "accts" | null>(null);
/** 未接入平台清单默认收起（页脚平铺太长） */
const slotsOpen = ref(false);

function toggleSection(name: "caps" | "profile" | "accts"): void {
  section.value = section.value === name ? null : name;
}

function toggleDetail(id: string) {
  expandedId.value = expandedId.value === id ? null : id;
  section.value = null; // 换行/收起时复位折叠小节，避免串行
  cancelEdit();
}
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">平台管理</h1>
        <p class="page-sub">本机接入的各家 AI 助手与其能力、调度执行时间。</p>
      </div>
      <div class="head-actions">
        <button
          class="btn btn--primary"
          :disabled="busyTarget !== null || !importableCount"
          @click="emit('importAll')"
        >接入全部{{ importableCount ? `（${importableCount}）` : "" }}</button>
      </div>
    </div>
  </header>

  <p
    v-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <section class="section" aria-label="平台名册">
    <div v-if="platforms.length" class="platform-wrap sheet">
      <table class="matrix">
        <thead>
          <tr>
            <th>平台编码</th>
            <th>平台名称</th>
            <th class="col-kind">平台类型</th>
            <th class="col-version">版本号</th>
            <th>平台状态</th>
            <th class="col-caps">能力</th>
            <th>调度执行时间</th>
            <th class="col-accounts">账户数</th>
            <th class="col-status">账户状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="platform in pagedPlatforms" :key="platform.id">
            <tr :class="{ 'is-selected': expandedId === platform.id }">
              <td class="code-cell"><code class="mono">{{ platform.id }}</code></td>
              <td>
                <PlatformBadge :name="platform.display" :color-index="faceOf(platform.id)" />
              </td>
              <td class="col-kind">
                <span v-if="platform.kind" class="tag tag--quiet">{{ kindText(platform.kind) }}</span>
                <span v-else class="faint">—</span>
              </td>
              <td class="num col-version">{{ platform.client_version ? `v${platform.client_version}` : "—" }}</td>
              <td>
                <span class="tag" :class="platform.active ? 'tag--ok' : 'tag--quiet'">
                  {{ platform.active ? "启用" : "已停用" }}
                </span>
              </td>
              <td class="col-caps">
                <span v-for="cap in platform.capabilities" :key="cap" class="tag tag--quiet cap-tag">
                  {{ capabilityText(cap) }}
                </span>
                <span v-if="!platform.capabilities.length" class="faint">—</span>
              </td>
              <td class="num">{{ platform.schedule_times.length ? platform.schedule_times.join("、") : "—" }}</td>
              <td class="num col-accounts">
                <span v-if="accountCount(platform)">{{ accountCount(platform) }}</span>
                <span v-else class="unimported">未接入</span>
              </td>
              <td class="col-status">
                <span
                  v-for="g in statusGroups(platform)"
                  :key="g.signal"
                  class="tag"
                  :class="`tag--${g.signal}`"
                >{{ signalText(g.signal) }} {{ g.count }}</span>
                <span v-if="!statusGroups(platform).length" class="faint">—</span>
              </td>
              <td @click.stop>
                <span class="row-actions">
                  <button
                    v-if="!platform.account_id"
                    class="btn btn--ghost"
                    :disabled="busyTarget !== null"
                    @click="emit('import', platform.id)"
                  >接入</button>
                  <button
                    v-else
                    class="btn btn--ghost"
                    :disabled="busyTarget !== null"
                    @click="emit('import', platform.id)"
                  >刷新</button>
                  <button v-if="platform.account_id" class="btn btn--ghost" @click="emit('jump', '账户管理')">去账户</button>
                  <button
                    class="btn btn--ghost"
                    :disabled="busyTarget !== null"
                    @click="toggleActive(platform)"
                  >{{ platform.active ? "停用" : "启用" }}</button>
                  <button class="btn btn--ghost" @click="toggleDetail(platform.id)">
                    {{ expandedId === platform.id ? "收起" : "详情" }}
                  </button>
                </span>
              </td>
            </tr>
            <tr v-if="expandedId === platform.id" class="detail-row">
              <td colspan="10" @click.stop>
                <div class="detail-fold">
                  <button
                    class="fold-head"
                    :aria-expanded="section === 'caps'"
                    @click="toggleSection('caps')"
                  >
                    <span class="fold-caret">{{ section === 'caps' ? '▾' : '▸' }}</span>
                    能力清单
                    <span class="fold-hint">{{ platform.capabilities.length }} 项</span>
                  </button>
                  <p v-if="section === 'caps'" class="fold-body mono">{{ platform.capabilities.join(" · ") || "—" }}</p>

                  <button
                    class="fold-head"
                    :aria-expanded="section === 'profile'"
                    @click="toggleSection('profile')"
                  >
                    <span class="fold-caret">{{ section === 'profile' ? '▾' : '▸' }}</span>
                    平台信息
                    <span class="fold-hint">
                      {{ platform.active ? "启用" : "已停用" }} · {{ platform.schedule_times.join("、") || "未排班" }}
                    </span>
                  </button>
                  <div v-if="section === 'profile'" class="fold-body">
                    <template v-if="editingId === platform.id">
                      <label class="edit-row">
                        <span class="edit-label">平台名称</span>
                        <input v-model="editName" class="input edit-name" maxlength="40" :disabled="busyTarget !== null" />
                        <button
                          v-if="platform.display !== platform.id"
                          class="btn btn--ghost"
                          :disabled="busyTarget !== null"
                          @click="resetName(platform)"
                        >恢复默认名</button>
                      </label>
                      <label class="edit-row">
                        <span class="edit-label">启用</span>
                        <input v-model="editActive" type="checkbox" :disabled="busyTarget !== null" />
                        <span class="fold-note">停用后不再定时领取，手动领取仍可</span>
                      </label>
                      <div class="edit-row">
                        <span class="edit-label">调度执行时间</span>
                        <div class="sched-edit">
                          <span v-for="(_, i) in editTimes" :key="i" class="sched-item">
                            <input v-model="editTimes[i]" class="input sched-input mono" type="time" :disabled="busyTarget !== null" />
                            <button class="btn btn--ghost" :disabled="busyTarget !== null" @click="removeSlot(i)">删除</button>
                          </span>
                          <button class="btn btn--ghost" :disabled="busyTarget !== null || editTimes.length >= 8" @click="addSlot">+ 添加时间</button>
                        </div>
                      </div>
                      <p class="fold-note">
                        清空时间并保存 = 该平台不再定时领取；{{ platform.schedule_overridden ? "当前调度为自定义" : "当前调度为平台默认" }}
                      </p>
                      <span class="row-actions">
                        <button class="btn btn--primary" :disabled="busyTarget !== null" @click="saveProfile(platform)">保存</button>
                        <button class="btn btn--ghost" :disabled="busyTarget !== null" @click="cancelEdit">取消</button>
                      </span>
                    </template>
                    <template v-else>
                      <p class="fold-line"><span class="edit-label">显示名</span>{{ platform.display }}</p>
                      <p class="fold-line"><span class="edit-label">平台状态</span>{{ platform.active ? "启用" : "已停用" }}</p>
                      <p class="fold-line">
                        <span class="edit-label">调度执行时间</span>{{ platform.schedule_times.join("、") || "未排班" }}
                        <span v-if="platform.schedule_overridden" class="tag tag--quiet sched-tag">自定义</span>
                      </p>
                      <p class="fold-note">平台编码、类型、版本、能力、凭据类型来自连接器探测，不可编辑。</p>
                      <span class="row-actions">
                        <button class="btn btn--ghost" :disabled="busyTarget !== null" @click="beginEdit(platform)">修改</button>
                      </span>
                    </template>
                  </div>

                  <button
                    class="fold-head"
                    :aria-expanded="section === 'accts'"
                    @click="toggleSection('accts')"
                  >
                    <span class="fold-caret">{{ section === 'accts' ? '▾' : '▸' }}</span>
                    账户（{{ accountCount(platform) }}）
                  </button>
                  <div v-if="section === 'accts'" class="fold-body">
                    <p class="fold-body mono">{{ accountsOf(platform).map((a) => a.account_id).join("、") || "—" }}</p>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <nav v-if="platforms.length" class="pager" aria-label="平台分页">
      <button class="btn btn--ghost" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span class="pager-info">
        第 {{ page }} / {{ totalPages }} 页 · 共 {{ platforms.length }} 个平台
      </span>
      <button class="btn btn--ghost" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
    </nav>

    <!-- 未接入平台（折叠收起：默认只显示一行标题，点开才平铺） -->
    <div v-if="emptyPlatforms.length" class="slots-fold">
      <button class="fold-head fold-head--page" :aria-expanded="slotsOpen" @click="slotsOpen = !slotsOpen">
        <span class="fold-caret">{{ slotsOpen ? "▾" : "▸" }}</span>
        尚未接入的平台（{{ emptyPlatforms.length }}）
        <span class="fold-hint">{{ slotsOpen ? "收起" : "展开可逐家接入" }}</span>
      </button>
      <ul v-if="slotsOpen" class="slots" aria-label="可接入平台">
        <li v-for="platform in emptyPlatforms" :key="platform.id">
          <button class="slot-row" :disabled="busyTarget !== null" @click="emit('import', platform.id)">
            <span class="slot-plus" aria-hidden="true">＋</span>
            接入 {{ platform.display }}
          </button>
        </li>
      </ul>
    </div>

    <p v-if="!platforms.length && loadError" class="quietline quietline--warn">
      平台列表读取失败：{{ loadError }}——请确认后端服务在运行（默认 127.0.0.1:8000）。
    </p>
    <p v-else-if="!platforms.length" class="quietline">
      还没有平台——「接入全部」把本机客户端接进来。
    </p>
  </section>
</template>

<style scoped>
.head { padding-top: var(--space-2); }
.head-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.head-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.platform-wrap { overflow-x: auto; }
.platform-wrap .matrix { min-width: 1120px; }
/* 自适应断点（2026-11-18）：窗口变窄逐级收起次要列，避免整表靠横向滚动才可读 */
@media (max-width: 1180px) {
  .platform-wrap .matrix { min-width: 860px; }
  .col-caps { display: none; }
}
@media (max-width: 980px) {
  .platform-wrap .matrix { min-width: 660px; }
  .col-kind, .col-version { display: none; }
}
@media (max-width: 760px) {
  .platform-wrap { overflow-x: visible; }
  .platform-wrap .matrix { min-width: 0; }
  .col-accounts, .col-status { display: none; }
  /* 极窄屏：动作收成 2×2 网格（堆四行会把表格拉得又长又稀） */
  .row-actions {
    display: grid;
    grid-template-columns: repeat(2, auto);
    justify-content: start;
    gap: 2px var(--space-2);
  }
  .row-actions .btn { padding: 2px var(--space-2); }
}

/* 详情折叠小节 + 页面级折叠（2026-11-18） */
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
.quietline--warn { color: var(--color-attention); }
.slots-fold { margin-top: var(--space-4); }
.fold-head--page { border-top: 1px solid var(--color-border); }

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
.code-cell code { font-size: var(--text-xs); color: var(--color-text-muted); }
.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-3);
}
.pager-info { font-size: var(--text-xs); color: var(--color-text-muted); }
.cap-tag { margin-right: var(--space-1); }
.faint { color: var(--color-text-faint); }
.unimported {
  color: var(--color-text-muted);
  border-bottom: 1px dashed var(--color-border);
}
.detail-row td {
  background: var(--color-surface-2);
  padding: var(--space-3) var(--space-4);
}
.slots {
  list-style: none;
  margin: var(--space-3) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.slot-row {
  box-sizing: border-box;
  width: 100%;
  border: 1.5px dashed var(--color-border);
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-size: var(--text-sm);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  cursor: pointer;
  transition:
    border-color var(--motion-base),
    color var(--motion-base);
}
.slot-row:hover:not(:disabled) { border-color: var(--color-accent); color: var(--color-accent); }
.slot-row:disabled { opacity: 0.45; cursor: not-allowed; }
.slot-plus { font-size: var(--text-lg); line-height: 1; }
</style>
