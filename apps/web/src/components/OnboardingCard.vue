<script setup lang="ts">
/**
 * 上手自检卡（2026-11-19）：
 * 两种形态，同一份数据决定——空库（一个账户都没有）显示三步引导；
 * 已有数据时显示自检清单（服务 / 平台接入 / 排班 / 账户健康）。
 *
 * 全部判断只消费既有投影：platform.account_ids / schedule_times / account.signal，
 * 不新开端点、不自造阈值（红线 2：健康分类由 core 出产）。
 * 收起状态记在 localStorage，下一份数据进来时若出现未完成项会自动展开。
 */
import { computed, ref, watch } from "vue";
import type { AccountItem, PageName, PlatformItem } from "../types";

const props = defineProps<{
  accounts: AccountItem[];
  platforms: PlatformItem[];
  loading: boolean;
  loadError: string;
}>();

const emit = defineEmits<{
  navigate: [page: PageName];
}>();

type Check = {
  key: string;
  name: string;
  detail: string;
  ok: boolean;
  action?: string;
  page?: PageName;
};

const HIDDEN_KEY = "butler.onboarding.hidden";
const collapsed = ref(localStorage.getItem(HIDDEN_KEY) === "1");

/* 已接入 = 至少有一个账户；未接入 = 平台还在但一个账户都没有 */
const docked = computed(() => props.platforms.filter((p) => p.account_ids.length > 0));
const undocked = computed(() =>
  props.platforms.filter((p) => p.account_ids.length === 0 && p.active),
);

const isFresh = computed(() => props.accounts.length === 0);

const checks = computed<Check[]>(() => {
  const serviceOk = !props.loadError;
  const dockedCount = docked.value.length;
  const totalActive = props.platforms.filter((p) => p.active).length;
  const scheduled = docked.value.filter((p) => p.schedule_times.length > 0);
  const unscheduled = docked.value.filter((p) => p.schedule_times.length === 0);
  const unwell = props.accounts.filter((a) => a.signal !== "ok");

  return [
    {
      key: "service",
      name: "本机服务",
      detail: serviceOk ? "在线" : "未连接——原因见页面顶部提示",
      ok: serviceOk,
    },
    {
      key: "docking",
      name: "平台接入",
      detail:
        dockedCount === 0
          ? `还没有接入任何平台（可用 ${totalActive} 家）`
          : undocked.value.length
            ? `已接入 ${dockedCount} / ${totalActive} 家，还差 ${undocked.value.length} 家`
            : `${dockedCount} 家全部接入`,
      ok: dockedCount > 0 && undocked.value.length === 0,
      action: "去接入",
      page: "平台管理",
    },
    {
      key: "schedule",
      name: "签到排班",
      detail:
        scheduled.length === 0
          ? "还没有平台排班——不排班只能手动领取"
          : unscheduled.length
            ? `${scheduled.length} / ${dockedCount} 家已排班：${unscheduled
                .map((p) => p.id)
                .join("、")} 还没排`
            : `${scheduled.length} 家已排班`,
      ok: dockedCount > 0 && unscheduled.length === 0,
      action: "去排班",
      page: "平台管理",
    },
    {
      key: "accounts",
      name: "账户健康",
      detail:
        props.accounts.length === 0
          ? "还没有账户"
          : unwell.length === 0
            ? `${props.accounts.length} 个账户全部正常`
            : `${props.accounts.length - unwell.length} 正常 · ${unwell.length} 需处理（${unwell
                .map((a) => a.account_id)
                .join("、")}）`,
      ok: props.accounts.length > 0 && unwell.length === 0,
      action: "去处理",
      page: "账户管理",
    },
  ];
});

const badCount = computed(() => checks.value.filter((c) => !c.ok).length);
const okCount = computed(() => checks.value.length - badCount.value);

/* 有未完成项时自动展开——避免用户上次收起后永远看不到问题 */
watch(
  badCount,
  (n) => {
    if (n > 0) collapsed.value = false;
  },
  { immediate: true },
);

function toggle() {
  collapsed.value = !collapsed.value;
  localStorage.setItem(HIDDEN_KEY, collapsed.value ? "1" : "0");
}
</script>

<template>
  <section class="onboard sheet" aria-label="上手自检">
    <header class="ob-head">
      <div class="ob-lead">
        <p class="ob-title">{{ isFresh ? "从这里开始" : "系统自检" }}</p>
        <p class="ob-sum" :class="badCount ? 'ob-sum--warn' : 'ob-sum--ok'">
          <template v-if="loading && !checks.length">检查中…</template>
          <template v-else-if="isFresh">三步把管家跑起来</template>
          <template v-else>
            {{ okCount }} 项正常<template v-if="badCount"> · {{ badCount }} 项需处理</template>
          </template>
        </p>
      </div>
      <button class="btn btn--ghost" :aria-expanded="!collapsed" @click="toggle">
        {{ collapsed ? "展开" : "收起" }}
      </button>
    </header>

    <!-- 空库：三步引导（带入口，不问人也能走完） -->
    <ol v-if="isFresh && !collapsed" class="ob-steps">
      <li>
        <span class="ob-step-no">1</span>
        <span class="ob-step-body">
          <span class="ob-step-name">接入平台</span>
          <span class="ob-step-hint">
            前提是本机已装好并登录对应客户端（豆包 / Qoder / Trae / WorkBuddy）。
            平台管理点「接入全部」一次接完。
          </span>
        </span>
        <button class="btn" @click="emit('navigate', '平台管理')">去接入</button>
      </li>
      <li>
        <span class="ob-step-no">2</span>
        <span class="ob-step-body">
          <span class="ob-step-name">设好签到时间</span>
          <span class="ob-step-hint">给每个平台排班（如 08:35），到点自动签；不排班只能手动点。</span>
        </span>
        <button class="btn" @click="emit('navigate', '平台管理')">去排班</button>
      </li>
      <li>
        <span class="ob-step-no">3</span>
        <span class="ob-step-body">
          <span class="ob-step-name">跑第一次签到</span>
          <span class="ob-step-hint">先手动点一次，确认链路通——成败都会进运行日志。</span>
        </span>
        <button class="btn" @click="emit('navigate', '账户管理')">去账户</button>
      </li>
    </ol>

    <!-- 已有数据：自检清单 -->
    <ul v-else-if="!collapsed" class="ob-list">
      <li v-for="item in checks" :key="item.key" class="ob-row">
        <span class="ob-dot" :class="item.ok ? 'ob-dot--ok' : 'ob-dot--warn'" aria-hidden="true" />
        <span class="ob-name">{{ item.name }}</span>
        <span class="ob-detail">{{ item.detail }}</span>
        <button
          v-if="!item.ok && item.action && item.page"
          class="btn btn--ghost"
          @click="emit('navigate', item.page)"
        >{{ item.action }}</button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.onboard {
  margin-top: var(--space-5);
  padding: var(--space-4) var(--space-5);
}
.ob-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}
.ob-lead { display: flex; align-items: baseline; gap: var(--space-3); flex-wrap: wrap; }
.ob-title { margin: 0; font-size: var(--text-md); font-weight: 600; color: var(--color-text); }
.ob-sum { margin: 0; font-size: var(--text-sm); }
.ob-sum--ok { color: var(--color-ok-ink); }
.ob-sum--warn { color: var(--color-attention-ink); }

.ob-steps { margin: var(--space-4) 0 0; padding: 0; list-style: none; display: grid; gap: var(--space-3); }
.ob-steps li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}
.ob-step-no {
  flex: none;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--color-accent-weak);
  color: var(--color-accent);
  font-size: var(--text-xs);
  font-weight: 600;
}
.ob-step-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.ob-step-name { font-size: var(--text-sm); font-weight: 600; color: var(--color-text); }
.ob-step-hint { font-size: var(--text-xs); color: var(--color-text-muted); line-height: 1.6; }

.ob-list { margin: var(--space-3) 0 0; padding: 0; list-style: none; }
.ob-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  font-size: var(--text-sm);
}
.ob-row + .ob-row { border-top: 1px solid var(--color-border); }
.ob-dot { flex: none; width: 7px; height: 7px; border-radius: 50%; }
.ob-dot--ok { background: var(--color-ok); }
.ob-dot--warn { background: var(--color-attention); }
.ob-name { flex: none; width: 92px; color: var(--color-text); }
.ob-detail { flex: 1; min-width: 0; color: var(--color-text-muted); }
</style>
