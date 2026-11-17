<script setup lang="ts">
/**
 * 账户矩阵表（ADR-010 / T9：自 AccountsPage 拆出，语义零变化）。
 * 9 列矩阵 + 筛选 + 批量条 + 行展开；状态染色只消费 core 出产的 signal 五分类，
 * 不认识 Status 字面量；repair_reason / evidence 直渲染不加工。
 */
import { computed, ref } from "vue";
import AppBadge from "./AppBadge.vue";
import AccountDetail from "./AccountDetail.vue";
import type { AccountItem, PlatformItem, RadarRow, RunItem } from "../types";
import { earliestExpiry, faceOf, fmtTime, isToday, signalText } from "../utils";

const props = defineProps<{
  accounts: AccountItem[];
  platforms: PlatformItem[];
  radar: RadarRow[];
  runs: RunItem[];
  busyTarget: string | null;
}>();

const emit = defineEmits<{
  claim: [target: string];
  health: [target: string];
  claimMany: [targets: string[]];
  scanSessions: [accountId: string];
}>();

/* ---- 筛选（只影响表格行与全选范围，不影响计数按钮）---- */
const appFilter = ref("");
const statusFilter = ref<"all" | "issues" | "ok">("all");

/* 关联以账户的 platform 为准；AppOut.account_id 只是排序后的首个账户，
 * 不能拿它判断同一平台的第 2、第 3 个账户（否则会误显示“未关联”）。 */
function appOf(account: AccountItem): PlatformItem | null {
  return (
    props.platforms.find((x) => x.id === account.platform_code) ??
    props.platforms.find((x) => x.account_ids?.includes(account.account_id)) ??
    null
  );
}

const filteredAccounts = computed(() =>
  props.accounts.filter((a) => {
    if (appFilter.value) {
      const platform = appOf(a);
      if (!platform || platform.id !== appFilter.value) return false;
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
    .filter((platform): platform is PlatformItem => Boolean(platform) && platform!.capabilities.includes("provision.run"))
    .map((platform) => platform.id),
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
    return row.packages.length ? { text: "已耗尽", low: false } : null;
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
  <section aria-label="账户矩阵">
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
      <select v-model="appFilter" class="input" aria-label="按平台筛选">
        <option value="">全部平台</option>
        <option v-for="platform in platforms" :key="platform.id" :value="platform.id">{{ platform.display }}</option>
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
            <th>平台</th>
            <th>账户</th>
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
                  :name="appOf(account)?.display ?? account.platform_code"
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
              <td class="col-extra row-time">
                {{ lastRunAtOf(account.account_id) ? fmtTime(lastRunAtOf(account.account_id)) : "—" }}
              </td>
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
                  :platform="appOf(account)"
                  :busy="busyTarget !== null"
                  @claim="emit('claim', $event)"
                  @health="emit('health', $event)"
                  @scan-sessions="emit('scanSessions', $event)"
                  @close="toggleDetail(account.account_id)"
                />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <p v-else-if="accounts.length" class="quietline">当前筛选没有匹配的账户——换个条件试试。</p>
    <p v-else class="quietline">还没有账户——到「平台」页导入平台。</p>
  </section>
</template>

<style scoped>
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
.matrix-wrap .matrix { min-width: 560px; }
.code { font-size: var(--text-xs); }
.faint { color: var(--color-text-faint); }
.detail-row td {
  background: var(--color-surface-2);
  padding: var(--space-3) var(--space-4);
}
@media (max-width: 900px) {
  .col-extra { display: none; }
}
</style>
