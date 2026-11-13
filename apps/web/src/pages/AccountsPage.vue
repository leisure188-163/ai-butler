<script setup lang="ts">
/**
 * 账号矩阵页（ADR-009 矩阵改版，产品新核心页）：
 * 全部应用 × 账号一屏管理——矩阵 + 右侧常驻待办栏。
 *
 * 渲染纪律（红线 2）：染色/文案只消费 core 出产的 signal 五分类；
 * 「今日动作」列用 signal 判定（ok=已完成 / attention·danger=未完成 / quiet=进行中），
 * 不认识 Status 字面量；repair_reason / evidence 直渲染不加工。
 * 数据全部来自壳下发的既有端点（契约零改动）。
 */
import { computed, ref } from "vue";
import AppBadge from "../components/AppBadge.vue";
import TodoRail from "../components/TodoRail.vue";
import AccountDetail from "../components/AccountDetail.vue";
import type { AccountItem, AppItem, RadarRow, RunItem } from "../types";
import { earliestExpiry, faceOf, fmtTime, isToday, signalText } from "../utils";

const props = defineProps<{
  accounts: AccountItem[];
  apps: AppItem[];
  radar: RadarRow[];
  pending: RunItem[];
  runs: RunItem[];
  busyTarget: string | null;
  msg: { text: string; tone: "ok" | "warn" } | null;
  loading: boolean;
  loadError: string;
  todayDone: { label: string; ok: number; total: number } | null;
}>();

const emit = defineEmits<{
  import: [target: string];
  claim: [target: string];
  health: [target: string];
  claimMany: [targets: string[]];
  importAll: [];
  claimAll: [];
}>();

/* ---- 页头：一句话结论（聚合只数数，语义词来自 signal）---- */
const headline = computed(() => {
  if (props.loading) return { strong: "正在打开账号面板", tail: "正在拉取最新状态" };
  if (props.loadError)
    return { strong: "暂时够不到服务", tail: "确认 server 已启动后，到侧栏点刷新" };
  if (props.pending.length > 0)
    return { strong: `${props.pending.length} 项待处理`, tail: "处理完即可清静" };
  if (props.accounts.length === 0)
    return { strong: "还没有接入任何应用", tail: "点一键导入，把本机客户端接进来" };
  const unwell = props.accounts.filter((a) => a.signal !== "ok").length;
  if (unwell > 0)
    return { strong: `${props.accounts.length} 个账号，${unwell} 个需要留意`, tail: "状态列与待办栏即现状" };
  return { strong: `${props.accounts.length} 个账号状态正常`, tail: "今日无事" };
});

/* ---- 批量计数（语义沿用旧卡包页：申报了能力的才计数，不虚报）---- */
const emptyApps = computed(() => props.apps.filter((a) => !a.account_id));
const importableCount = computed(() => emptyApps.value.length);
const claimableCount = computed(
  () => props.apps.filter((a) => a.account_id && a.capabilities.includes("provision.run")).length,
);
const claimableTargets = computed(
  () =>
    new Set(
      props.apps
        .filter((a) => a.account_id && a.capabilities.includes("provision.run"))
        .map((a) => a.id),
    ),
);

/* ---- 筛选（只影响表格行与全选范围，不影响计数按钮）---- */
const appFilter = ref("");
const statusFilter = ref<"all" | "issues" | "ok">("all");

function appOf(account: AccountItem): AppItem | null {
  return props.apps.find((x) => x.account_id === account.account_id) ?? null;
}

const filteredAccounts = computed(() =>
  props.accounts.filter((a) => {
    if (appFilter.value) {
      const app = appOf(a);
      if (!app || app.id !== appFilter.value) return false;
    }
    if (statusFilter.value === "issues" && a.signal === "ok") return false;
    if (statusFilter.value === "ok" && a.signal !== "ok") return false;
    return true;
  }),
);

/* ---- 勾选与批量（批量领取走 claimMany，壳里逐个顺序执行）---- */
const selected = ref<Set<string>>(new Set());

const allFilteredSelected = computed(
  () =>
    filteredAccounts.value.length > 0 &&
    filteredAccounts.value.every((a) => selected.value.has(a.account_id)),
);

function toggleAll() {
  const next = new Set(selected.value);
  if (allFilteredSelected.value) {
    for (const a of filteredAccounts.value) next.delete(a.account_id);
  } else {
    for (const a of filteredAccounts.value) next.add(a.account_id);
  }
  selected.value = next;
}

function toggleOne(accountId: string) {
  const next = new Set(selected.value);
  if (next.has(accountId)) next.delete(accountId);
  else next.add(accountId);
  selected.value = next;
}

const selectedClaimTargets = computed(() =>
  filteredAccounts.value
    .filter((a) => selected.value.has(a.account_id))
    .map((a) => appOf(a))
    .filter((app): app is AppItem => Boolean(app) && app!.capabilities.includes("provision.run"))
    .map((app) => app.id),
);

/* ---- 详情展开（点行 toggle；交互单元格 @click.stop 不触发）---- */
const expandedId = ref<string | null>(null);

function toggleDetail(accountId: string) {
  expandedId.value = expandedId.value === accountId ? null : accountId;
}

/* ---- 今日动作列（本地自然日；判定只看 signal，不做 Status 映射）---- */
const todayRunsByAccount = computed(() => {
  const map = new Map<string, RunItem[]>();
  for (const r of props.runs) {
    if (!isToday(r.started_at)) continue;
    const list = map.get(r.account_id) ?? [];
    list.push(r);
    map.set(r.account_id, list);
  }
  return map;
});

const todayAction = computed(() => {
  const result = new Map<string, { label: string; cls: "ok" | "attention" | "quiet"; reason: string | null }>();
  for (const a of props.accounts) {
    const runs = todayRunsByAccount.value.get(a.account_id) ?? [];
    if (!runs.length) {
      result.set(a.account_id, { label: "未做", cls: "quiet", reason: null });
    } else if (runs.some((r) => r.signal === "ok")) {
      result.set(a.account_id, { label: "✓ 已完成", cls: "ok", reason: null });
    } else if (runs.some((r) => r.signal !== "quiet")) {
      const bad = runs.find((r) => r.signal !== "quiet");
      result.set(a.account_id, {
        label: "✗ 未完成",
        cls: "attention",
        reason: bad?.repair_reason ?? null,
      });
    } else {
      result.set(a.account_id, { label: "进行中", cls: "quiet", reason: null });
    }
  }
  return result;
});

/* ---- 额度列（radar 数据面：最紧的活跃包一行 + 低额标记；无数据如实「—」）---- */
function ratioOf(remaining: number, total: number): number {
  return total > 0 ? remaining / total : 1;
}

function quotaOf(accountId: string): { text: string; low: boolean } | null {
  const row = props.radar.find((r) => r.account_id === accountId);
  if (!row) return null;
  const active = row.packages.filter((p) => p.remaining > 0);
  if (!active.length) {
    return row.packages.length
      ? { text: "已耗尽", low: false }
      : null;
  }
  const tightest = active.reduce((min, p) =>
    ratioOf(p.remaining, p.total) < ratioOf(min.remaining, min.total) ? p : min,
  );
  const more = active.length > 1 ? ` +${active.length - 1}` : "";
  return {
    text: `${tightest.remaining}/${tightest.total} ${tightest.unit}${more}`,
    low: row.quota_low.includes(tightest.name),
  };
}

/* ---- 凭据列 / 最近操作列 ---- */
function credNoticeOf(account: AccountItem): boolean {
  return account.credentials.some((c) => c.signal === "notice");
}

function lastRunAtOf(accountId: string): string | null {
  return props.runs.find((r) => r.account_id === accountId)?.started_at ?? null;
}
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">{{ headline.strong }}</h1>
        <p class="page-sub">{{ headline.tail }}</p>
      </div>
      <span class="row-actions">
        <button
          class="btn"
          :disabled="busyTarget !== null || !importableCount"
          @click="emit('importAll')"
        >一键导入{{ importableCount ? `（${importableCount}）` : "" }}</button>
        <button
          class="btn btn--primary"
          :disabled="busyTarget !== null || !claimableCount"
          @click="emit('claimAll')"
        >一键领取{{ claimableCount ? `（${claimableCount}）` : "" }}</button>
      </span>
    </div>
  </header>

  <p
    v-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <div class="rack">
    <section class="main" aria-label="账号矩阵">
      <!-- 批量条：勾选 >0 才出现 -->
      <p v-if="selected.size" class="batchbar sheet">
        已选 {{ selected.size }}
        <button
          class="btn"
          :disabled="busyTarget !== null || !selectedClaimTargets.length"
          @click="emit('claimMany', selectedClaimTargets)"
        >批量领取（{{ selectedClaimTargets.length }}）</button>
        <button class="btn btn--ghost" @click="selected = new Set()">取消选择</button>
      </p>

      <!-- 筛选 -->
      <p class="filters">
        <select v-model="appFilter" class="input" aria-label="按应用筛选">
          <option value="">全部应用</option>
          <option v-for="app in apps" :key="app.id" :value="app.id">{{ app.display }}</option>
        </select>
        <select v-model="statusFilter" class="input" aria-label="按状态筛选">
          <option value="all">全部状态</option>
          <option value="issues">需处理</option>
          <option value="ok">正常</option>
        </select>
      </p>

      <!-- 矩阵表 -->
      <div v-if="filteredAccounts.length" class="matrix-wrap sheet">
        <table class="matrix">
          <thead>
            <tr>
              <th class="col-check">
                <input
                  type="checkbox"
                  class="checkbox"
                  :checked="allFilteredSelected"
                  aria-label="全选"
                  @change="toggleAll"
                />
              </th>
              <th>应用</th>
              <th>账号</th>
              <th>状态</th>
              <th>今日动作</th>
              <th class="col-extra">额度</th>
              <th class="col-extra">凭据</th>
              <th class="col-extra">最近操作</th>
              <th>动作</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="account in filteredAccounts" :key="account.account_id">
              <tr
                :class="{ 'is-selected': expandedId === account.account_id }"
                @click="toggleDetail(account.account_id)"
              >
                <td class="col-check" @click.stop>
                  <input
                    type="checkbox"
                    class="checkbox"
                    :checked="selected.has(account.account_id)"
                    :aria-label="`选择 ${account.account_id}`"
                    @change="toggleOne(account.account_id)"
                  />
                </td>
                <td>
                  <AppBadge
                    :name="appOf(account)?.display ?? '未关联应用'"
                    :color-index="faceOf(account.account_id)"
                  />
                </td>
                <td class="mono code">{{ account.account_id }}</td>
                <td>
                  <span class="tag" :class="`tag--${account.signal}`">
                    {{ signalText(account.signal) }}
                  </span>
                </td>
                <td>
                  <span class="tag" :class="`tag--${todayAction.get(account.account_id)?.cls}`">
                    {{ todayAction.get(account.account_id)?.label }}
                  </span>
                  <p v-if="todayAction.get(account.account_id)?.reason" class="row-sub">
                    {{ todayAction.get(account.account_id)?.reason }}
                  </p>
                </td>
                <td class="col-extra num">
                  <template v-if="quotaOf(account.account_id)">
                    {{ quotaOf(account.account_id)!.text }}
                    <span v-if="quotaOf(account.account_id)!.low" class="tag tag--attention">低额</span>
                  </template>
                  <span v-else class="faint">—</span>
                </td>
                <td class="col-extra">
                  <template v-if="earliestExpiry(account)">
                    {{ fmtTime(earliestExpiry(account)) }} 到期
                    <span v-if="credNoticeOf(account)" class="tag tag--notice">临期</span>
                  </template>
                  <span v-else class="faint">—</span>
                </td>
                <td class="col-extra row-time">{{ lastRunAtOf(account.account_id) ? fmtTime(lastRunAtOf(account.account_id)) : "—" }}</td>
                <td @click.stop>
                  <span class="row-actions">
                    <button
                      v-if="appOf(account)?.capabilities.includes('provision.run')"
                      class="btn btn--ghost"
                      :disabled="busyTarget !== null"
                      @click="emit('claim', appOf(account)!.id)"
                    >领取</button>
                    <button
                      v-if="appOf(account)?.capabilities.includes('health.check')"
                      class="btn btn--ghost"
                      :disabled="busyTarget !== null"
                      @click="emit('health', appOf(account)!.id)"
                    >体检</button>
                    <button class="btn btn--ghost" @click="toggleDetail(account.account_id)">
                      {{ expandedId === account.account_id ? "收起" : "详情" }}
                    </button>
                  </span>
                </td>
              </tr>
              <tr v-if="expandedId === account.account_id" class="detail-row">
                <td :colspan="9" @click.stop>
                  <AccountDetail
                    :account="account"
                    :app="appOf(account)"
                    :busy="busyTarget !== null"
                    @claim="emit('claim', $event)"
                    @health="emit('health', $event)"
                    @close="toggleDetail(account.account_id)"
                  />
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <p v-else-if="accounts.length" class="quietline">当前筛选没有匹配的账号——换个条件试试。</p>

      <!-- 未导入应用的虚位邀请行 -->
      <ul v-if="emptyApps.length" class="slots" aria-label="可导入应用">
        <li v-for="app in emptyApps" :key="app.id">
          <button class="slot-row" :disabled="busyTarget !== null" @click="emit('import', app.id)">
            <span class="slot-plus" aria-hidden="true">＋</span>
            导入 {{ app.display }}
          </button>
        </li>
      </ul>

      <p v-if="!accounts.length && !emptyApps.length" class="quietline">
        还没有接入任何应用——一键导入把本机客户端接进来。
      </p>
    </section>

    <aside class="side" aria-label="待办">
      <TodoRail
        :pending="pending"
        :accounts="accounts"
        :today-done="todayDone"
        :claimable="claimableTargets"
        @claim="emit('claim', $event)"
      />
    </aside>
  </div>
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

/* 左矩阵 + 右待办栏（细线分隔；≤900px 待办栏下沉） */
.rack {
  margin-top: var(--space-6);
  display: flex;
  align-items: flex-start;
}
.main { flex: 1.6; min-width: 0; }
.side {
  flex: 1;
  min-width: 260px;
  max-width: 320px;
  border-left: 1px solid var(--color-border);
  padding-left: var(--space-6);
  position: sticky;
  top: var(--space-6);
}

.batchbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
  margin-bottom: var(--space-3);
}
.filters {
  display: flex;
  gap: var(--space-2);
  margin: 0 0 var(--space-3);
}
.matrix-wrap { overflow-x: auto; }
.code { font-size: var(--text-xs); }
.faint { color: var(--color-text-faint); }
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

@media (max-width: 900px) {
  .rack { flex-direction: column; }
  .side {
    position: static;
    max-width: none;
    width: 100%;
    border-left: none;
    border-top: 1px solid var(--color-border);
    padding-left: 0;
    padding-top: var(--space-4);
    margin-top: var(--space-2);
  }
  .col-extra { display: none; }
}
</style>
