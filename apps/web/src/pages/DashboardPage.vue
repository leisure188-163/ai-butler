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
import OnboardingCard from "../components/OnboardingCard.vue";
import QuickPanel from "../components/QuickPanel.vue";
import TodoRail from "../components/TodoRail.vue";
import type { AccountItem, PlatformItem, PageName, RadarRow, RunItem, Signal } from "../types";
import { isToday, signalText } from "../utils";

const props = defineProps<{
  accounts: AccountItem[];
  platforms: PlatformItem[];
  runs: RunItem[];
  pending: RunItem[];
  radarRows: RadarRow[];
  todayDone: { label: string; ok: number; total: number } | null;
  claimable: Set<string>;
  busyTarget: string | null;
  loading: boolean;
  loadError: string;
  loadedAt: string;
}>();

const emit = defineEmits<{
  claim: [target: string];
  health: [target: string];
  navigate: [page: PageName];
  repair: [target: string, accountId: string];
}>();

function onRepair(target: string, accountId: string) {
  emit("repair", target, accountId);
}

/* ---- 今日一句话结论（逐字沿用原账户页谓词，按词表 v2 换词）---- */
const headline = computed(() => {
  if (props.loading) return { strong: "正在打开签到概览", tail: "正在拉取最新状态" };
  /* 读不到数据时用中性表述：界面应像「今天没有数据」，而不是变成一张报错页
     （故障原因已在顶部状态行说清，这里不再复述成第二个报错位置） */
  if (props.loadError && !props.accounts.length)
    return { strong: "今日暂无数据", tail: "服务恢复后点刷新会重新拉取" };
  if (props.pending.length > 0)
    return { strong: `${props.pending.length} 项待处理`, tail: "处理完即可清静" };
  if (props.accounts.length === 0)
    return { strong: "还没有接入任何平台", tail: "到「平台管理」页接入全部，把本机客户端接进来" };
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

/* ---- 下次班次（v6.2 ③）：全平台班次时刻并集中取下一个未来时刻——
   时刻来自 platforms 真实排班（schedule_times），不到点不编造状态 ---- */
const shiftTimes = computed(() =>
  [...new Set(props.platforms.flatMap((a) => a.schedule_times))]
    .filter((t) => /^\d{1,2}:\d{2}$/.test(t))
    .sort(),
);

const nextShift = computed(() => {
  const all = shiftTimes.value.map((t) => {
    const [h, m] = t.split(":").map(Number);
    return { t, m: h * 60 + m };
  });
  if (!all.length) return null;
  const now = new Date();
  const mins = now.getHours() * 60 + now.getMinutes();
  const todayLeft = all.filter((x) => x.m > mins);
  if (todayLeft.length) {
    return {
      time: todayLeft[0].t,
      sub: `约 ${todayLeft[0].m - mins} 分钟后 · 今日还剩 ${todayLeft.length} 个班次`,
    };
  }
  return {
    time: all[0].t,
    sub: `明日最早 · ${1440 + all[0].m - mins} 分钟后`,
  };
});

/* ---- 签到日历条带（v6.2）：账户行 × 近 30 天列，任一班次 ok = 绿——
   连签/断签一眼化；数据 = ledger 真实 run，不编造（红线 2）---- */
const CAL_DAYS = 30;

const calDays = computed(() =>
  Array.from({ length: CAL_DAYS }, (_, i) => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - (CAL_DAYS - 1 - i));
    return d;
  }),
);

const calRows = computed(() => {
  const byAccount: Record<string, Record<string, "ok" | "fail">> = {};
  for (const r of props.runs) {
    if (r.kind !== "provision.run") continue;
    const key = new Date(r.started_at).toDateString();
    const row = (byAccount[r.account_id] ??= {});
    if (r.signal === "ok" || row[key] !== "ok") {
      row[key] = r.signal === "ok" ? "ok" : "fail";
    }
  }
  const seen = new Set(Object.keys(byAccount));
  const order = [
    ...props.accounts.map((a) => a.account_id).filter((id) => seen.has(id)),
    ...Object.keys(byAccount).filter((id) => !props.accounts.some((a) => a.account_id === id)),
  ];
  return order.map((id) => ({ account: id, cells: byAccount[id] }));
});

function calDotClass(
  cells: Record<string, "ok" | "fail"> | undefined,
  day: Date,
): string {
  const state = cells?.[day.toDateString()];
  return state ? `cal-dot--${state}` : "cal-dot--none";
}

/* ---- 额度水位（v6.2）：流量 KPI 卡迷你水位条——最低活跃包 remaining/total ---- */
const waterLevel = computed(() => {
  let min: number | null = null;
  for (const row of props.radarRows) {
    for (const pkg of row.packages) {
      if (pkg.total <= 0) continue;
      const level = Math.max(0, Math.min(1, pkg.remaining / pkg.total));
      if (min === null || level < min) min = level;
    }
  }
  return min;
});
/* 低水位色随 core 谓词（quota_low），前端不自定阈值（红线 2） */
const quotaLow = computed(() => props.radarRows.some((r) => r.quota_low.length > 0));

/* ---- KPI 卡（v6）：数字是锚点——健康/动作取数为主数字，流量/日志为文本卡；
   v7 加图标片与占比环（环只消费真实比值，无数据如实不画）---- */
const healthyCount = computed(
  () => props.accounts.filter((a) => a.signal === "ok").length,
);
const unwellCount = computed(
  () => props.accounts.length - healthyCount.value,
);
const healthRatio = computed(() =>
  props.accounts.length ? healthyCount.value / props.accounts.length : null,
);
const actionRatio = computed(() =>
  todayActions.value.total
    ? todayActions.value.done / todayActions.value.total
    : null,
);
const RING_C = 94.2; // r=15 周长

function ringDash(ratio: number): string {
  return `${Math.max(0, Math.min(1, ratio)) * RING_C} ${RING_C}`;
}
const trafficMain = computed(() => {
  if (!props.radarRows.length) return "尚未采集";
  const lowest = props.radarRows.find((r) => r.quota_low.length > 0);
  return lowest ? `最低额度 ${lowest.account_id}` : "额度未见预警";
});
const trafficSub = computed(() => {
  if (!props.radarRows.length) return "到「用量管理」页发起采集";
  const collected = props.loadedAt
    || props.radarRows
      .map((r) => r.collected_at ?? "")
      .filter(Boolean)
      .sort()
      .pop()
    || "—";
  return `最近采集于 ${collected}`;
});
</script>

<template>
  <header class="head">
    <h1 class="page-title">{{ headline.strong }}</h1>
    <p class="page-sub">{{ headline.tail }}</p>
  </header>

  <OnboardingCard
    :accounts="accounts"
    :platforms="platforms"
    :loading="loading"
    :load-error="loadError"
    @navigate="emit('navigate', $event)"
  />

  <section class="section" aria-label="速览">
    <h2 class="section-title">速览</h2>
    <div class="kpi-grid">
      <div class="kpi" aria-label="账户健康">
        <div class="kpi-head">
          <span class="kpi-chip kpi-chip--ok" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 13.5S2.5 10 2.5 6.2A3 3 0 0 1 8 4.4a3 3 0 0 1 5.5 1.8C13.5 10 8 13.5 8 13.5Z" /></svg>
          </span>
          <p class="kpi-label">账户健康</p>
          <svg
            v-if="healthRatio !== null"
            class="kpi-ring"
            viewBox="0 0 36 36"
            width="34"
            height="34"
            role="img"
            :aria-label="`健康占比 ${Math.round(healthRatio * 100)}%`"
          >
            <circle cx="18" cy="18" r="15" fill="none" stroke="var(--color-surface-2)" stroke-width="4" />
            <circle
              cx="18" cy="18" r="15" fill="none"
              :stroke="unwellCount ? 'var(--color-attention)' : 'var(--color-ok)'"
              stroke-width="4" stroke-linecap="round"
              :stroke-dasharray="ringDash(healthRatio)"
              transform="rotate(-90 18 18)"
            />
          </svg>
        </div>
        <p class="kpi-value" :class="unwellCount ? 'kpi-value--attention' : 'kpi-value--ok'">
          {{ loading ? "—" : healthyCount }}<span
            v-if="!loading"
            class="kpi-total"
          >/{{ props.accounts.length }}</span>
        </p>
        <p class="kpi-sub">
          <span
            v-for="g in healthGroups"
            :key="g.signal"
            class="tag"
            :class="`tag--${g.signal}`"
          >{{ signalText(g.signal) }} {{ g.count }}</span>
          <span v-if="!healthGroups.length" class="faint">—</span>
        </p>
      </div>
      <div class="kpi" aria-label="今日自动动作">
        <div class="kpi-head">
          <span class="kpi-chip kpi-chip--accent" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M9 2 3.5 9H7l-.8 5L12 7H8.5L9 2Z" /></svg>
          </span>
          <p class="kpi-label">今日自动动作</p>
          <svg
            v-if="actionRatio !== null"
            class="kpi-ring"
            viewBox="0 0 36 36"
            width="34"
            height="34"
            role="img"
            :aria-label="`完成占比 ${Math.round(actionRatio * 100)}%`"
          >
            <circle cx="18" cy="18" r="15" fill="none" stroke="var(--color-surface-2)" stroke-width="4" />
            <circle
              cx="18" cy="18" r="15" fill="none" stroke="var(--color-accent)"
              stroke-width="4" stroke-linecap="round"
              :stroke-dasharray="ringDash(actionRatio)"
              transform="rotate(-90 18 18)"
            />
          </svg>
        </div>
        <p class="kpi-value">{{ todayActions.total ? todayActions.done : "0" }}</p>
        <p class="kpi-sub">
          {{ todayActions.total
            ? `${todayActions.undone} 未完成 · 共 ${todayActions.total}`
            : "今日还没有动作" }}
        </p>
      </div>
      <div class="kpi" aria-label="用量">
        <div class="kpi-head">
          <span class="kpi-chip kpi-chip--quiet" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M8 2.5s4 4.6 4 7.4a4 4 0 0 1-8 0c0-2.8 4-7.4 4-7.4Z" /></svg>
          </span>
          <p class="kpi-label">流量</p>
        </div>
        <p class="kpi-value kpi-value--sm">{{ trafficMain }}</p>
        <div
          v-if="waterLevel !== null"
          class="meter"
          role="img"
          :aria-label="`最低额度水位 ${Math.round(waterLevel * 100)}%`"
        >
          <span
            class="meter-fill"
            :class="quotaLow ? 'meter-fill--low' : ''"
            :style="{ width: `${Math.max(4, Math.round(waterLevel * 100))}%` }"
          />
        </div>
        <p class="kpi-sub">{{ trafficSub }}</p>
      </div>
      <div class="kpi" aria-label="下次班次">
        <div class="kpi-head">
          <span class="kpi-chip kpi-chip--notice" aria-hidden="true">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="8" cy="8" r="6" /><path d="M8 4.5V8l2.5 1.5" /></svg>
          </span>
          <p class="kpi-label">下次班次</p>
        </div>
        <p class="kpi-value mono" v-if="nextShift">{{ nextShift.time }}</p>
        <p class="kpi-value kpi-value--sm" v-else>未排班</p>
        <p class="kpi-sub">
          {{ nextShift ? nextShift.sub : "到「平台管理」页为平台排班" }}
        </p>
      </div>
    </div>
  </section>

  <div class="dash-cols">
    <section class="section dash-todo" aria-label="待办">
      <h2 class="section-title">待办</h2>
      <TodoRail
        :pending="pending"
        :accounts="accounts"
        :today-done="todayDone"
        :claimable="claimable"
        @claim="emit('claim', $event)"
        @navigate="emit('navigate', $event)"
        @repair="onRepair"
      />
    </section>
    <aside class="dash-side">
      <QuickPanel :platforms="platforms" @navigate="emit('navigate', $event)" />
    </aside>
  </div>

  <section class="section" aria-label="签到日历">
    <h2 class="section-title">近 30 天签到</h2>
    <div class="sheet cal-sheet">
      <div
        v-for="row in calRows"
        :key="row.account"
        class="cal-row"
      >
        <span class="cal-account mono">{{ row.account }}</span>
        <span class="cal-dots" role="img" :aria-label="`${row.account} 近 30 天签到点阵`">
          <i
            v-for="(day, i) in calDays"
            :key="i"
            class="cal-dot"
            :class="[
              calDotClass(row.cells, day),
              { 'cal-dot--today': i === calDays.length - 1 },
            ]"
          />
        </span>
      </div>
      <p v-if="!calRows.length" class="cal-empty faint">还没有领取记录——签到后这里会出现日历条带</p>
      <div class="cal-legend">
        <span class="cal-dot cal-dot--ok" /> 已签
        <span class="cal-dot cal-dot--fail" /> 未成
        <span class="cal-dot cal-dot--none" /> 未跑
        <span class="cal-hint">右侧为今天</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.head { padding-top: var(--space-2); }
.kpi-total {
  font-size: var(--text-lg);
  font-weight: 500;
  color: var(--color-text-faint);
  margin-left: 2px;
}
.faint { color: var(--color-text-faint); }
/* v6.3 双栏：左待办 + 右快捷/班次；≤900px 随侧栏断点转单列 */
.dash-cols {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: var(--space-4);
  align-items: start;
}
.dash-todo { margin-top: var(--space-5); }
.dash-side { margin-top: var(--space-5); }
@media (max-width: 900px) {
  .dash-cols { grid-template-columns: minmax(0, 1fr); }
}
</style>
