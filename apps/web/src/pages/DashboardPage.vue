<script setup lang="ts">
/**
 * 仪表盘（ADR-010 六页 IA 默认页）：一屏回答「今天有事要做吗」。
 * 三块 = 今日一句话结论 + TodoRail 三节 + 速览四行；全部复用既有端点数据，
 * 不开新端点，聚合只做纯 computed（A3-01 v2 §2）。
 *
 * 渲染纪律（红线 2）：健康分布只消费 core 出产的 signal 五分类，
 * 不认识 Status / HealthLevel 字面量；空数据如实留白，不编造结论。
 */
import { computed } from "vue";
import TodoRail from "../components/TodoRail.vue";
import type { AccountItem, AppItem, PageName, RadarRow, RunItem, Signal } from "../types";
import { fmtTime, isToday, signalText } from "../utils";

const props = defineProps<{
  accounts: AccountItem[];
  apps: AppItem[];
  runs: RunItem[];
  pending: RunItem[];
  radarRows: RadarRow[];
  todayDone: { label: string; ok: number; total: number } | null;
  claimable: Set<string>;
  busyTarget: string | null;
  msg: { text: string; tone: "ok" | "warn" } | null;
  loading: boolean;
  loadError: string;
  loadedAt: string;
}>();

const emit = defineEmits<{
  claim: [target: string];
  health: [target: string];
  navigate: [page: PageName];
}>();

/* ---- 今日一句话结论（逐字沿用原账户页谓词，按词表 v2 换词）---- */
const headline = computed(() => {
  if (props.loading) return { strong: "正在打开仪表盘", tail: "正在拉取最新状态" };
  if (props.loadError)
    return { strong: "暂时够不到服务", tail: "确认 server 已启动后点刷新" };
  if (props.pending.length > 0)
    return { strong: `${props.pending.length} 项待处理`, tail: "处理完即可清静" };
  if (props.accounts.length === 0)
    return { strong: "还没有接入任何应用", tail: "到「应用」页一键导入，把本机客户端接进来" };
  const unwell = props.accounts.filter((a) => a.signal !== "ok").length;
  if (unwell > 0)
    return {
      strong: `${props.accounts.length} 个账户，${unwell} 个需要留意`,
      tail: "速览与待办栏即现状",
    };
  return { strong: `${props.accounts.length} 个账户状态正常`, tail: "今日无事" };
});

/* ---- 速览四行（纯计数/取数，不做语义加工）---- */
const signals: Signal[] = ["ok", "notice", "attention", "danger", "quiet"];

const healthGroups = computed(() =>
  signals
    .map((signal) => ({
      signal,
      count: props.accounts.filter((a) => a.signal === signal).length,
    }))
    .filter((g) => g.count > 0),
);

const todayActions = computed(() => {
  const today = props.runs.filter((r) => isToday(r.started_at));
  return {
    done: today.filter((r) => r.signal === "ok").length,
    undone: today.filter((r) => r.signal !== "ok").length,
    total: today.length,
  };
});

const trafficGlance = computed(() => {
  if (!props.radarRows.length) return "尚未采集";
  const collected = props.loadedAt
    || props.radarRows
      .map((r) => r.collected_at ?? "")
      .filter(Boolean)
      .sort()
      .pop()
    || "—";
  const lowest = props.radarRows.find((r) => r.quota_low.length > 0);
  return `最近采集于 ${collected}，${lowest ? `最低额度 ${lowest.account_id}` : "额度未见预警"}`;
});

const lastLog = computed(() => {
  const first = props.runs[0];
  return first ? `${fmtTime(first.started_at)} · ${first.kind}` : "—";
});

const glanceRows = computed(() => [
  { title: "账户健康分布", value: "" },
  { title: "今日自动动作", value: todayActions.value.total
    ? `${todayActions.value.done} 完成 · ${todayActions.value.undone} 未完成`
    : "今日还没有动作" },
  { title: "流量", value: trafficGlance.value },
  { title: "最近一条日志", value: lastLog.value },
]);
</script>

<template>
  <header class="head">
    <h1 class="page-title">{{ headline.strong }}</h1>
    <p class="page-sub">{{ headline.tail }}</p>
  </header>

  <p
    v-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <section class="section" aria-label="速览">
    <h2 class="section-title">速览</h2>
    <ul class="rows sheet">
      <li v-for="row in glanceRows" :key="row.title" class="row">
        <span class="row-main">
          <p class="row-title">{{ row.title }}</p>
          <p v-if="row.title === '账户健康分布'" class="row-sub glance-tags">
            <span
              v-for="g in healthGroups"
              :key="g.signal"
              class="tag"
              :class="`tag--${g.signal}`"
            >{{ signalText(g.signal) }} {{ g.count }}</span>
            <span v-if="!healthGroups.length" class="faint">—</span>
          </p>
        </span>
        <span v-if="row.value" class="row-time glance-value">{{ row.value }}</span>
      </li>
    </ul>
  </section>

  <section class="section" aria-label="待办">
    <h2 class="section-title">待办</h2>
    <TodoRail
      :pending="pending"
      :accounts="accounts"
      :today-done="todayDone"
      :claimable="claimable"
      @claim="emit('claim', $event)"
      @navigate="emit('navigate', $event)"
    />
  </section>
</template>

<style scoped>
.head { padding-top: var(--space-2); }
.glance-tags { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-2); }
.glance-value { white-space: normal; }
.faint { color: var(--color-text-faint); }
</style>
