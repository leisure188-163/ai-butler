<script setup lang="ts">
/**
 * 账户分组视图（平台/账户关联重设计 v1）：按平台分组呈现账户，
 * 组头 = 归属锚点（平台身份 + 健康汇总 + 整组领取），组内 = 账户明细。
 * 与 MatrixTable 共用 useAccountRows 派生逻辑——同数据两视图零漂移。
 * 行内修复入口复用 ADR-015 两步引导：先重新登录，再点「我已登录，立即重试」。
 */
import { computed, ref, watch } from "vue";
import ActionIcon from "./ActionIcon.vue";
import PlatformBadge from "./PlatformBadge.vue";
import AccountDetail from "./AccountDetail.vue";
import { useAccountRows } from "../composables/useAccountRows";
import { faceOf, fmtTime, signalText } from "../utils";
import { platformIcon } from "../utils/platformIcons";
import type { AccountItem, PlatformItem, RadarRow, RunItem, Signal } from "../types";

const props = defineProps<{
  accounts: AccountItem[];
  platforms: PlatformItem[];
  radar: RadarRow[];
  runs: RunItem[];
  busyTarget: string | null;
  initialPlatform?: string | null;
}>();

const emit = defineEmits<{
  claim: [target: string];
  health: [target: string];
  claimMany: [targets: string[]];
  scanSessions: [accountId: string];
  repair: [target: string, accountId: string];
  rename: [accountId: string, alias: string];
}>();

const {
  appOf,
  accountLabel,
  todayAction,
  quotaOf,
  earliestExpiry,
  credNoticeOf,
  lastRunAtOf,
} = useAccountRows({
  accounts: computed(() => props.accounts),
  platforms: computed(() => props.platforms),
  radar: computed(() => props.radar),
  runs: computed(() => props.runs),
});

/* 筛选：平台（可被平台页跳转预置）+ 状态 + 关键字 */
const appFilter = ref(props.initialPlatform ?? "");
const statusFilter = ref<"all" | "issues" | "ok">("all");
const keyword = ref("");
watch(
  () => props.initialPlatform,
  (code) => {
    if (code) appFilter.value = code;
  },
);

const filtered = computed(() =>
  props.accounts.filter((a) => {
    if (appFilter.value && a.platform_code !== appFilter.value) return false;
    if (statusFilter.value === "issues" && a.signal === "ok") return false;
    if (statusFilter.value === "ok" && a.signal !== "ok") return false;
    if (keyword.value) {
      const q = keyword.value.toLowerCase();
      if (
        !a.account_id.toLowerCase().includes(q) &&
        !a.account_name.toLowerCase().includes(q)
      ) return false;
    }
    return true;
  }),
);

const signals: Signal[] = ["ok", "notice", "attention", "danger", "quiet"];

const groups = computed(() => {
  const order = new Map(props.platforms.map((p, i) => [p.id, i]));
  const buckets = new Map<string, AccountItem[]>();
  for (const a of filtered.value) {
    const code = a.platform_code || appOf(a)?.id || "未知平台";
    const list = buckets.get(code) ?? [];
    list.push(a);
    buckets.set(code, list);
  }
  return [...buckets.entries()]
    .map(([code, list]) => ({
      code,
      platform: props.platforms.find((p) => p.id === code) ?? null,
      accounts: list,
      health: signals
        .map((signal) => ({ signal, count: list.filter((a) => a.signal === signal).length }))
        .filter((g) => g.count > 0),
      claimable: props.platforms.some(
        (p) => p.id === code && p.capabilities.includes("provision.run"),
      ),
    }))
    .sort(
      (a, b) =>
        (order.get(a.code) ?? props.platforms.length) -
          (order.get(b.code) ?? props.platforms.length) ||
        a.code.localeCompare(b.code),
    );
});

/* 勾选（批量领取按平台 target，与 claimMany 既有语义一致） */
const selected = ref<Set<string>>(new Set());
const groupAllSelected = (code: string) => {
  const list = filtered.value.filter((a) => a.platform_code === code);
  return list.length > 0 && list.every((a) => selected.value.has(a.account_id));
};
function toggleGroup(code: string) {
  const next = new Set(selected.value);
  const list = filtered.value.filter((a) => a.platform_code === code);
  if (groupAllSelected(code)) list.forEach((a) => next.delete(a.account_id));
  else list.forEach((a) => next.add(a.account_id));
  selected.value = next;
}
function toggleOne(id: string) {
  const next = new Set(selected.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selected.value = next;
}
const batchTargets = computed(() => {
  const codes = new Set(
    filtered.value
      .filter((a) => selected.value.has(a.account_id))
      .map((a) => a.platform_code),
  );
  return props.platforms
    .filter((p) => codes.has(p.id) && p.capabilities.includes("provision.run"))
    .map((p) => p.id);
});
function clearSelection() {
  selected.value = new Set();
}

/* 折叠 / 详情 / 修复两步引导 */
const collapsed = ref<Set<string>>(new Set());
function toggleCollapse(code: string) {
  const next = new Set(collapsed.value);
  if (next.has(code)) next.delete(code);
  else next.add(code);
  collapsed.value = next;
}
const expandedId = ref<string | null>(null);
function toggleDetail(id: string) {
  expandedId.value = expandedId.value === id ? null : id;
}
const repairingId = ref<string | null>(null);
function confirmRepair(account: AccountItem) {
  const platform = appOf(account);
  if (!platform) return;
  repairingId.value = null;
  emit("repair", platform.id, account.account_id);
}
</script>

<template>
  <section aria-label="账户分组矩阵">
    <div class="toolbar">
      <input v-model="keyword" class="input search" type="search" placeholder="搜索账户名 / ID" aria-label="搜索账户" />
      <select v-model="appFilter" class="input" aria-label="按平台筛选">
        <option value="">全部平台</option>
        <option v-for="p in platforms" :key="p.id" :value="p.id">{{ p.platform_name }}</option>
      </select>
      <select v-model="statusFilter" class="input" aria-label="按状态筛选">
        <option value="all">全部状态</option>
        <option value="issues">需处理</option>
        <option value="ok">正常</option>
      </select>
    </div>

    <p v-if="selected.size" class="batchbar sheet">
      已选 {{ selected.size }}
      <button class="btn" :disabled="busyTarget !== null || !batchTargets.length" @click="emit('claimMany', batchTargets)">
        批量领取（{{ batchTargets.length }}）
      </button>
      <button class="btn btn--ghost" @click="clearSelection">取消选择</button>
    </p>

    <div v-for="g in groups" :key="g.code" class="group sheet">
      <div class="group-head">
        <button class="caret" :aria-expanded="!collapsed.has(g.code)" @click="toggleCollapse(g.code)">
          {{ collapsed.has(g.code) ? "▸" : "▾" }}
        </button>
        <PlatformBadge :name="g.platform?.platform_name ?? g.code" :color-index="faceOf(g.code)" :icon="platformIcon(g.platform)" />
        <code class="mono group-code">{{ g.code }}</code>
        <span class="group-health">
          <span v-for="h in g.health" :key="h.signal" class="tag" :class="`tag--${h.signal}`">
            {{ signalText(h.signal) }} {{ h.count }}
          </span>
          <span class="group-count num">{{ g.accounts.length }} 个账户</span>
        </span>
        <span class="grow"></span>
        <button
          v-if="g.claimable"
          class="btn btn--ghost"
          :disabled="busyTarget !== null"
          @click="emit('claim', g.code)"
        >领取该组</button>
      </div>

      <div v-if="!collapsed.has(g.code)" class="group-body">
        <table class="matrix group-matrix">
          <thead>
            <tr>
              <th class="col-check">
                <input type="checkbox" class="checkbox" :checked="groupAllSelected(g.code)" :aria-label="`全选 ${g.code}`" @change="toggleGroup(g.code)" />
              </th>
              <th>账户</th>
              <th>健康</th>
              <th>今日动作</th>
              <th class="col-extra">额度</th>
              <th class="col-extra">凭据</th>
              <th class="col-extra">最近操作</th>
              <th>动作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="a in g.accounts" :key="a.account_id">
              <tr :class="{ 'is-selected': expandedId === a.account_id }" @click="toggleDetail(a.account_id)">
                <td class="col-check" @click.stop>
                  <input type="checkbox" class="checkbox" :checked="selected.has(a.account_id)" :aria-label="`选择 ${a.account_id}`" @change="toggleOne(a.account_id)" />
                </td>
                <td>
                  <div class="acct-name">{{ accountLabel(a) }}</div>
                  <div class="acct-id mono">{{ a.account_id }}</div>
                </td>
                <td class="col-state"><span class="tag" :class="`tag--${a.signal}`">{{ signalText(a.signal) }}</span></td>
                <td>
                  <span class="tag" :class="`tag--${todayAction.get(a.account_id)?.cls}`">
                    {{ todayAction.get(a.account_id)?.label }}
                  </span>
                  <p v-if="todayAction.get(a.account_id)?.reason" class="row-fix">
                    {{ todayAction.get(a.account_id)?.reason }}
                  </p>
                  <button
                    v-if="todayAction.get(a.account_id)?.reason"
                    class="btn btn--ghost fix-btn"
                    @click.stop="repairingId = repairingId === a.account_id ? null : a.account_id"
                  >去修复</button>
                  <div v-if="repairingId === a.account_id" class="repair-panel" @click.stop>
                    <p class="repair-steps">
                      1. 在 {{ g.platform?.platform_name ?? g.code }} 客户端退出登录，再重新登录<br />
                      2. 点「我已登录，立即重试」——会先重新读取本机凭据
                    </p>
                    <span class="repair-actions">
                      <button class="btn" :disabled="busyTarget !== null" @click="confirmRepair(a)">我已登录，立即重试</button>
                      <button class="btn btn--ghost" @click="repairingId = null">取消</button>
                    </span>
                  </div>
                </td>
                <td class="col-extra col-quota">
                  <template v-if="quotaOf(a.account_id)">
                    <div class="quota num">{{ quotaOf(a.account_id)!.text }}</div>
                    <div class="meter"><span class="meter-fill" :class="{ 'meter-fill--low': quotaOf(a.account_id)!.low }" :style="{ width: `${(quotaOf(a.account_id)!.ratio ?? 0) * 100}%` }"></span></div>
                  </template>
                  <span v-else class="faint">—</span>
                </td>
                <td class="col-extra col-cred">
                  <template v-if="earliestExpiry(a)">
                    <span class="num">{{ fmtTime(earliestExpiry(a)) }} 到期</span>
                    <span v-if="credNoticeOf(a)" class="tag tag--notice">临期</span>
                  </template>
                  <span v-else class="faint">—</span>
                </td>
                <td class="col-extra col-time row-time">{{ lastRunAtOf(a.account_id) ? fmtTime(lastRunAtOf(a.account_id)) : "—" }}</td>
                <td class="col-actions" @click.stop>
                  <span class="row-actions">
                    <button
                      v-if="g.claimable"
                      class="icon-btn"
                      title="领取该平台今日额度"
                      aria-label="领取"
                      :disabled="busyTarget !== null"
                      @click="emit('claim', g.code)"
                    >
                      <ActionIcon name="claim" />
                    </button>
                    <button
                      v-if="g.platform?.capabilities.includes('health.check')"
                      class="icon-btn"
                      title="检查凭据与登录态"
                      aria-label="体检"
                      :disabled="busyTarget !== null"
                      @click="emit('health', g.code)"
                    >
                      <ActionIcon name="health" />
                    </button>
                    <span
                      class="expand-hint"
                      :class="{ 'is-open': expandedId === a.account_id }"
                      aria-hidden="true"
                    >
                      <ActionIcon name="expand" />
                    </span>
                  </span>
                </td>
              </tr>
              <tr v-if="expandedId === a.account_id" class="detail-row">
                <td colspan="8" @click.stop>
                  <AccountDetail
                    :account="a"
                    :platform="g.platform"
                    :busy="busyTarget !== null"
                    @claim="emit('claim', $event)"
                    @health="emit('health', $event)"
                    @scan-sessions="emit('scanSessions', $event)"
                    @rename="(id: string, alias: string) => emit('rename', id, alias)"
                    @close="toggleDetail(a.account_id)"
                  />
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <p v-if="!groups.length && accounts.length" class="quietline">没有匹配的账户——换个条件试试。</p>
    <p v-else-if="!accounts.length" class="quietline">还没有账户——到「平台管理」页接入平台。</p>
  </section>
</template>

<style scoped>
.toolbar { display: flex; gap: var(--space-2); margin-bottom: var(--space-3); flex-wrap: wrap; }
.search { flex: 0 1 16rem; }
.batchbar { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) var(--space-4); font-size: var(--text-sm); margin-bottom: var(--space-3); }
.group { margin-bottom: var(--space-3); overflow: hidden; }
.group-head { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-4); background: var(--color-surface-2); flex-wrap: wrap; }
.caret { border: 0; background: none; color: var(--color-text-muted); font-size: var(--text-sm); cursor: pointer; padding: 0 var(--space-1); }
.group-code { font-size: var(--text-xs); color: var(--color-text-muted); }
.group-health { display: inline-flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.group-count { font-size: var(--text-xs); color: var(--color-text-muted); }
.grow { flex: 1; }
.group-body { border-top: 1px solid var(--border, var(--color-border)); }
.group-matrix { min-width: 720px; }
.group-body { overflow-x: auto; }
.group-matrix .col-check { width: 2.75rem; }
/* 列表规范 07：表头居中，短值列内容跟着居中；账户与今日动作仍左对齐 */
.group-matrix th { text-align: center; }
.group-matrix td.col-state,
td.col-quota, td.col-cred, td.col-time, td.col-actions { text-align: center; }
.group-matrix .row-actions { justify-content: center; }
.expand-hint {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  color: var(--color-text-faint);
  transition: transform 0.15s ease;
}
.expand-hint.is-open { transform: rotate(180deg); }
.acct-name { font-size: var(--text-sm); font-weight: 600; }
.acct-id { font-size: var(--text-xs); color: var(--color-text-muted); }
.quota { font-size: var(--text-xs); }
.faint { color: var(--color-text-faint); }
.row-fix { margin: 2px 0 0; color: var(--color-attention-ink); font-size: var(--text-xs); max-width: 20rem; }
.fix-btn { font-size: var(--text-xs); padding: 0 var(--space-1); }
.repair-panel { margin-top: var(--space-2); padding: var(--space-2) var(--space-3); background: var(--color-attention-weak); border-radius: var(--radius-sm); max-width: 24rem; }
.repair-steps { margin: 0 0 var(--space-2); font-size: var(--text-xs); color: var(--color-attention-ink); }
.repair-actions { display: inline-flex; gap: var(--space-2); }
.detail-row td { background: var(--color-surface-2); padding: var(--space-3) var(--space-4); }
@media (max-width: 900px) {
  .col-extra { display: none; }
  .group-matrix { min-width: 0; }
  .row-fix { max-width: 14rem; }
}
</style>
