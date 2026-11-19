<script setup lang="ts">
/**
 * 账户矩阵表（ADR-010 / T9：自 AccountsPage 拆出，语义零变化）。
 * 9 列矩阵 + 筛选 + 批量条 + 行展开；状态染色只消费 core 出产的 signal 五分类，
 * 不认识 Status 字面量；repair_reason / evidence 直渲染不加工。
 */
import { computed, ref, watch } from "vue";
import ActionIcon from "@/shared/components/ActionIcon.vue";
import PlatformBadge from "@/domains/platforms/PlatformBadge.vue";
import AccountDetail from "@/domains/accounts/AccountDetail.vue";
import { useAccountRows } from "@/domains/accounts/useAccountRows";
import type { AccountItem, PlatformItem, RadarRow, RunItem } from "@/shared/types";
import { faceOf, fmtTime, signalText } from "@/shared/utils/format";
import { platformIcon } from "@/domains/platforms/platformIcons";

const props = defineProps<{
  accounts: AccountItem[];
  platforms: PlatformItem[];
  radar: RadarRow[];
  runs: RunItem[];
  busyTarget: string | null;
  /** 平台页「查看账户」下钻预置的平台编码 */
  initialPlatform?: string | null;
}>();

const emit = defineEmits<{
  claim: [target: string];
  health: [target: string];
  claimMany: [targets: string[]];
  scanSessions: [accountId: string];
  rename: [accountId: string, alias: string];
  remove: [accountId: string];
}>();

/* 派生逻辑单源：与 AccountGrouped 共用 useAccountRows（红线 2：端零映射） */
const { appOf, accountLabel, todayAction, quotaOf, earliestExpiry, credNoticeOf, lastRunAtOf } =
  useAccountRows({
    accounts: computed(() => props.accounts),
    platforms: computed(() => props.platforms),
    radar: computed(() => props.radar),
    runs: computed(() => props.runs),
  });

/* ---- 筛选（只影响表格行与全选范围，不影响计数按钮）---- */
const appFilter = ref(props.initialPlatform ?? "");
const statusFilter = ref<"all" | "issues" | "ok">("all");
watch(
  () => props.initialPlatform,
  (code) => {
    if (code) appFilter.value = code;
  },
);

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
        <option v-for="platform in platforms" :key="platform.id" :value="platform.id">{{ platform.platform_name }}</option>
      </select>
      <select v-model="statusFilter" class="input" aria-label="按状态筛选">
        <option value="all">全部状态</option>
        <option value="issues">需处理</option>
        <option value="ok">正常</option>
      </select>
    </p>

    <!-- 矩阵表 -->
    <div class="matrix-wrap sheet">
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
            <th class="col-platform">平台</th>
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
          <tr v-if="!filteredAccounts.length">
            <td class="table-empty" colspan="9">
              {{ accounts.length ? "当前筛选没有匹配的账户" : "暂无账户" }}
            </td>
          </tr>
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
              <td class="col-platform">
                <PlatformBadge
                  :name="appOf(account)?.platform_name ?? account.platform_code"
                  :color-index="faceOf(account.account_id)"
                  :icon="platformIcon(appOf(account))"
                />
              </td>
              <td>
                <div class="acct-name">{{ accountLabel(account) }}</div>
                <div class="mono acct-id">{{ account.account_id }}</div>
              </td>
              <td class="col-state">
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
              <td class="col-extra col-quota">
                <template v-if="quotaOf(account.account_id)">
                  <div class="num quota-text">{{ quotaOf(account.account_id)!.text }}</div>
                  <div class="meter">
                    <span
                      class="meter-fill"
                      :class="{ 'meter-fill--low': quotaOf(account.account_id)!.low }"
                      :style="{ width: `${(quotaOf(account.account_id)!.ratio ?? 0) * 100}%` }"
                    ></span>
                  </div>
                </template>
                <span v-else class="faint">—</span>
              </td>
              <td class="col-extra col-cred">
                <template v-if="earliestExpiry(account)">
                  {{ fmtTime(earliestExpiry(account)) }} 到期
                  <span v-if="credNoticeOf(account)" class="tag tag--notice">临期</span>
                </template>
                <span v-else class="faint">—</span>
              </td>
              <td class="col-extra col-time row-time">
                {{ lastRunAtOf(account.account_id) ? fmtTime(lastRunAtOf(account.account_id)) : "—" }}
              </td>
              <td class="col-actions" @click.stop>
                <span class="row-actions">
                  <button
                    v-if="appOf(account)?.capabilities.includes('provision.run')"
                    class="icon-btn"
                    title="领取该平台今日额度"
                    aria-label="领取"
                    :disabled="busyTarget !== null"
                    @click="emit('claim', appOf(account)!.id)"
                  >
                    <ActionIcon name="claim" />
                  </button>
                  <button
                    v-if="appOf(account)?.capabilities.includes('health.check')"
                    class="icon-btn"
                    title="检查凭据与登录态"
                    aria-label="体检"
                    :disabled="busyTarget !== null"
                    @click="emit('health', appOf(account)!.id)"
                  >
                    <ActionIcon name="health" />
                  </button>
                  <button
                    class="icon-btn icon-btn--danger"
                    title="删除账户（关联凭据一并删除）"
                    aria-label="删除账户"
                    :disabled="busyTarget !== null"
                    @click="emit('remove', account.account_id)"
                  >
                    <ActionIcon name="trash" />
                  </button>
                  <!-- 展开提示不是第二个入口：整行点击即开合，这里只用箭头状态暗示 -->
                  <span
                    class="expand-hint"
                    :class="{ 'is-open': expandedId === account.account_id }"
                    aria-hidden="true"
                  >
                    <ActionIcon name="expand" />
                  </span>
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
                  @rename="(id: string, alias: string) => emit('rename', id, alias)"
                  @close="toggleDetail(account.account_id)"
                />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
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
.matrix-wrap .matrix { min-width: 620px; }
/* 列表规范 07：表头居中；短值列（状态/额度/凭据/最近/动作）内容跟着居中，
   平台与账户、今日动作这类长文本列两边都左对齐 */
.matrix-wrap .matrix th { text-align: center; }
.matrix-wrap .matrix td.col-state,
td.col-quota, td.col-cred, td.col-time, td.col-actions { text-align: center; }
/* .row-actions 是 flex 容器，td 的 text-align 管不到它，得单独居中 */
.matrix-wrap .matrix .row-actions { justify-content: center; }
/* 展开提示（非按钮）：整行点击开合，箭头只表达状态 */
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
.quota-text { font-size: var(--text-xs); }
.quota-text + .meter { max-width: 8rem; margin-top: 4px; }
.faint { color: var(--color-text-faint); }
.detail-row td {
  background: var(--color-surface-2);
  padding: var(--space-3) var(--space-4);
}
@media (max-width: 900px) {
  .col-extra { display: none; }
  /* 收起三列后不再撑 620px 底宽，否则窗口够宽也要横向滚动 */
  .matrix-wrap .matrix { min-width: 0; }
  .col-last, .matrix th:last-child, .matrix td:last-child { min-width: 4.75rem; }
  /* 失败原因别把整行撑成竖排长条：两行封顶，全文看账户详情 */
  .row-sub {
    max-width: 7.5rem;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
}
/* ≤760：平台名列收起（账户 ID 前缀已是平台编码），把宽度让给账户与动作 */
@media (max-width: 760px) {
  .col-platform { display: none; }
}
</style>
