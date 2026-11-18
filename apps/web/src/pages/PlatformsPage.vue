<script setup lang="ts">
/**
 * 平台页（ADR-010 六页 IA）：本机接入的各家 AI 助手名册。
 * 六列表 + 虚线邀请行 + 行展开；数据全部来自契约既有 AppOut/AccountOut，
 * 零新端点、零语义加工（能力标签只做协议 kind 的直译，signal 只消费分类）。
 */
import { computed, ref, watch } from "vue";
import PlatformBadge from "../components/PlatformBadge.vue";
import PlatformDetail from "../components/PlatformDetail.vue";
import PlatformFilters from "../components/PlatformFilters.vue";
import CustomPlatformForm from "../components/CustomPlatformForm.vue";
import type {
  AccountItem,
  CustomPlatformDraft,
  PageName,
  PlatformItem,
  PlatformQuery,
  Signal,
} from "../types";
import { faceOf, signalText } from "../utils";

const props = defineProps<{
  platforms: PlatformItem[];
  accounts: AccountItem[];
  /** 自定义平台编码集合（2026-11-18）：名册里的「自定义」徽章与删除入口据此判定 */
  customCodes: string[];
  busyTarget: string | null;
  msg: { text: string; tone: "ok" | "warn" } | null;
  loading: boolean;
  loadError: string;
}>();

const emit = defineEmits<{
  claim: [target: string];
  import: [target: string];
  importAll: [];
  savePlatform: [
    target: string,
    patch: { platform_name?: string | null; active?: boolean; times?: string[] | null },
  ];
  saveCustom: [draft: CustomPlatformDraft];
  removeCustom: [code: string];
  jump: [page: PageName];
}>();

/* 自定义平台（2026-11-18）：内置清单之外的平台由用户自建；表单折叠在页头下方 */
const showCustomForm = ref(false);

function isCustom(id: string): boolean {
  return props.customCodes.includes(id);
}

function confirmRemove(id: string): void {
  if (!window.confirm(`删除自定义平台 ${id}？历史台账保留，但不再排班。`)) return;
  emit("removeCustom", id);
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

/** 接入前提（新手提示）：只按契约字段直译，不在这里判定能不能接 */
function accessHint(platform: PlatformItem): string {
  if (platform.kind === "client") return "需本机已安装并登录该客户端";
  if (platform.kind === "web") return "需先在浏览器里登录该平台";
  return "需先登录对应客户端或浏览器";
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

/* 检索（2026-11-18）：关键字 + 状态 + 类型 + 排序，纯前端过滤，零新端点 */
const query = ref<PlatformQuery>({ keyword: "", status: "all", kind: "all", sort: "code" });

const filteredPlatforms = computed(() => {
  const keyword = query.value.keyword.trim().toLowerCase();
  const list = props.platforms.filter((platform) => {
    if (query.value.status !== "all" && platform.active !== (query.value.status === "active")) {
      return false;
    }
    if (query.value.kind !== "all" && platform.kind !== query.value.kind) return false;
    if (!keyword) return true;
    return (
      platform.id.toLowerCase().includes(keyword) || platform.display.toLowerCase().includes(keyword)
    );
  });
  const sorted = [...list];
  if (query.value.sort === "name") {
    sorted.sort((a, b) => a.display.localeCompare(b.display, "zh"));
  } else if (query.value.sort === "accounts") {
    sorted.sort((a, b) => accountCount(b) - accountCount(a) || a.id.localeCompare(b.id));
  } else {
    sorted.sort((a, b) => a.id.localeCompare(b.id));
  }
  return sorted;
});

/* 分页（2026-11-18）：每页 10 条——接入平台变多后一屏放不下 */
const PAGE_SIZE = 10;
const page = ref(1);

const totalPages = computed(() =>
  Math.max(1, Math.ceil(filteredPlatforms.value.length / PAGE_SIZE)),
);

const pagedPlatforms = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE;
  return filteredPlatforms.value.slice(start, start + PAGE_SIZE);
});

/* 换筛选条件回第一页；平台增减时把页码收敛回合法区间（不跳页、不空页） */
watch(query, () => { page.value = 1; }, { deep: true });
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
/** 未接入平台清单默认收起（页脚平铺太长） */
const slotsOpen = ref(false);

function toggleDetail(id: string) {
  expandedId.value = expandedId.value === id ? null : id;
}
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">平台管理</h1>
        <p class="page-sub">
          平台来自内置连接器（共 {{ platforms.length }} 家）——本机装好并登录对应客户端后即可接入。
        </p>
      </div>
      <div class="head-actions">
        <button class="btn" :disabled="busyTarget !== null" @click="showCustomForm = !showCustomForm">
          {{ showCustomForm ? "收起表单" : "＋ 自定义平台" }}
        </button>
        <button
          class="btn btn--primary"
          :disabled="busyTarget !== null || !importableCount"
          @click="emit('importAll')"
        >接入全部{{ importableCount ? `（${importableCount}）` : "" }}</button>
      </div>
    </div>
  </header>

  <CustomPlatformForm
    v-if="showCustomForm"
    :saving="busyTarget !== null"
    @save="(draft) => emit('saveCustom', draft)"
    @close="showCustomForm = false"
  />

  <p
    v-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <section class="section" aria-label="平台名册">
    <PlatformFilters
      v-if="platforms.length"
      v-model:keyword="query.keyword"
      v-model:status="query.status"
      v-model:kind="query.kind"
      v-model:sort="query.sort"
      :total="platforms.length"
      :matched="filteredPlatforms.length"
    />

    <div v-if="pagedPlatforms.length" class="platform-wrap sheet">
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
              <td class="code-cell">
                <code class="mono">{{ platform.id }}</code>
                <span v-if="isCustom(platform.id)" class="tag tag--notice custom-tag">自定义</span>
              </td>
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
                  <button
                    v-if="platform.account_id && platform.capabilities.includes('provision.run')"
                    class="btn btn--ghost"
                    :disabled="busyTarget !== null"
                    @click="emit('claim', platform.id)"
                  >立即领取</button>
                  <button v-if="platform.account_id" class="btn btn--ghost" @click="emit('jump', '账户管理')">去账户</button>
                  <button
                    class="btn btn--ghost"
                    :disabled="busyTarget !== null"
                    @click="toggleActive(platform)"
                  >{{ platform.active ? "停用" : "启用" }}</button>
                  <button class="btn btn--ghost" @click="toggleDetail(platform.id)">
                    {{ expandedId === platform.id ? "收起" : "详情" }}
                  </button>
                  <button
                    v-if="isCustom(platform.id)"
                    class="btn btn--ghost"
                    :disabled="busyTarget !== null"
                    @click="confirmRemove(platform.id)"
                  >删除</button>
                </span>
              </td>
            </tr>
            <tr v-if="expandedId === platform.id" class="detail-row">
              <td colspan="10" @click.stop>
                <PlatformDetail
                  :platform="platform"
                  :accounts="accountsOf(platform)"
                  :busy="busyTarget !== null"
                  @save="(patch) => emit('savePlatform', platform.id, patch)"
                />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <nav v-if="platforms.length" class="pager" aria-label="平台分页">
      <button class="btn btn--ghost" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span class="pager-info">
        第 {{ page }} / {{ totalPages }} 页 · 共 {{ filteredPlatforms.length }} 个平台
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
            <span class="slot-body">
              <span class="slot-name">接入 {{ platform.display }}（{{ platform.id }}）</span>
              <span class="slot-hint">{{ accessHint(platform) }}</span>
            </span>
          </button>
        </li>
      </ul>
    </div>

    <p v-if="platforms.length && !filteredPlatforms.length" class="quietline">
      没有匹配的平台——换个关键字，或点「清除筛选」。
    </p>
    <p v-if="!platforms.length && loadError" class="quietline quietline--warn">
      平台列表读取失败：{{ loadError }}——请确认后端服务在运行（默认 127.0.0.1:8000）。
    </p>
    <p v-else-if="!platforms.length" class="quietline">
      还没有平台——「接入全部」把本机客户端接进来。
    </p>
  </section>
</template>

<style scoped>
/* 自定义平台徽章（2026-11-18）：编码列内联，不单开一列 */
.code-cell {
  white-space: nowrap;
}
.custom-tag {
  margin-left: 6px;
}

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

/* 页面级折叠（页脚「尚未接入的平台」）；平台详情折叠已迁 PlatformDetail.vue */
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
.quietline--warn { color: var(--color-attention); }
.slots-fold { margin-top: var(--space-4); }
.fold-head--page { border-top: 1px solid var(--color-border); }

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
.slot-body { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; }
.slot-name { color: inherit; font-size: var(--text-sm); }
.slot-hint { color: var(--color-text-faint); font-size: var(--text-xs); }
</style>
