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
  syncAll: [targets: string[]];
  jump: [page: PageName];
}>();

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

function toggleDetail(id: string) {
  expandedId.value = expandedId.value === id ? null : id;
}
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">平台</h1>
        <p class="page-sub">本机接入的各家 AI 助手与其能力、调度执行时间。</p>
      </div>
      <div class="head-actions">
        <button
          class="btn btn--ghost"
          :disabled="busyTarget !== null || !platforms.length"
          @click="emit('syncAll', platforms.map((platform) => platform.id))"
        >同步全部</button>
        <button
          class="btn btn--primary"
          :disabled="busyTarget !== null || !importableCount"
          @click="emit('importAll')"
        >一键导入{{ importableCount ? `（${importableCount}）` : "" }}</button>
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
            <th>能力</th>
            <th>调度执行时间</th>
            <th>账户数</th>
            <th>状态汇总</th>
            <th>动作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="platform in pagedPlatforms" :key="platform.id">
            <tr :class="{ 'is-selected': expandedId === platform.id }" @click="toggleDetail(platform.id)">
              <td class="code-cell"><code class="mono">{{ platform.id }}</code></td>
              <td>
                <PlatformBadge :name="platform.display" :color-index="faceOf(platform.id)" />
                <span class="kind-tag tag tag--quiet">{{ kindText(platform.kind) }}</span>
                <span v-if="platform.client_version" class="faint version-text">v{{ platform.client_version }}</span>
              </td>
              <td>
                <span v-for="cap in platform.capabilities" :key="cap" class="tag tag--quiet cap-tag">
                  {{ capabilityText(cap) }}
                </span>
                <span v-if="!platform.capabilities.length" class="faint">—</span>
              </td>
              <td class="num">{{ platform.schedule_times.length ? platform.schedule_times.join("、") : "—" }}</td>
              <td class="num">
                <span v-if="accountCount(platform)">{{ accountCount(platform) }}</span>
                <span v-else class="unimported">未导入</span>
              </td>
              <td>
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
                  >导入</button>
                  <button
                    v-else
                    class="btn btn--ghost"
                    :disabled="busyTarget !== null"
                    @click="emit('import', platform.id)"
                  >同步</button>
                  <button v-if="platform.account_id" class="btn btn--ghost" @click="emit('jump', '账户')">去账户</button>
                  <button class="btn btn--ghost" @click="toggleDetail(platform.id)">
                    {{ expandedId === platform.id ? "收起" : "详情" }}
                  </button>
                </span>
              </td>
            </tr>
            <tr v-if="expandedId === platform.id" class="detail-row">
              <td colspan="7" @click.stop>
                <ul class="rows">
                  <li class="row">
                    <span class="row-main">
                      <p class="row-title">能力清单</p>
                      <p class="row-sub mono">{{ platform.capabilities.join(" · ") || "—" }}</p>
                    </span>
                  </li>
                  <li class="row">
                    <span class="row-main">
                      <p class="row-title">调度执行时间</p>
                      <p class="row-sub">{{ platform.schedule_times.join("、") || "—" }}</p>
                    </span>
                  </li>
                  <li class="row">
                    <span class="row-main">
                      <p class="row-title">该平台账户（{{ accountCount(platform) }}）</p>
                      <p class="row-sub mono">
                        {{ accountsOf(platform).map((a) => a.account_id).join("、") || "—" }}
                      </p>
                    </span>
                    <button class="btn btn--ghost" @click="emit('jump', '账户')">去账户</button>
                  </li>
                </ul>
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

    <!-- 未接入平台的虚位邀请行（从账户页迁入，ADR-010 §3） -->
    <ul v-if="emptyPlatforms.length" class="slots" aria-label="可导入平台">
      <li v-for="platform in emptyPlatforms" :key="platform.id">
        <button class="slot-row" :disabled="busyTarget !== null" @click="emit('import', platform.id)">
          <span class="slot-plus" aria-hidden="true">＋</span>
          导入 {{ platform.display }}
        </button>
      </li>
    </ul>

    <p v-if="!platforms.length" class="quietline">
      还没有平台——一键导入把本机客户端接进来。
    </p>
  </section>
</template>

<style scoped>
.kind-tag { margin-left: var(--space-2); }
.version-text { margin-left: var(--space-1); font-size: var(--text-xs); }
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
.platform-wrap .matrix { min-width: 880px; }
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
