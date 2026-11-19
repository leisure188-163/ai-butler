<script setup lang="ts">
/**
 * 流量页（ADR-010 六页 IA；原用量页改名换词）：
 * 各家账户余额、额度流水与耗尽预测，一页看全。
 *
 * 渲染纪律（红线 2）：余额/预测/流水都是 server 投影的 core 出产数据，
 * 页面不做语义加工——forecast 缺失（不足两帧差分）如实显示「采集中」；
 * quota_low 是 core 谓词（is_quota_low）出产的包名列表，只做布尔标记；
 * aggregate_summary 是连接器原话，折叠直渲染不重排。
 * 数据流：壳下发（rows/collecting 由 App.vue 持有，轮询自动覆盖），本组件纯展示。
 */
import type { PackageRow, RadarRow } from "../types";
import { faceOf, fmtTime } from "../utils";
import PlatformBadge from "../components/PlatformBadge.vue";

defineProps<{
  rows: RadarRow[];
  loading: boolean;
  collecting: boolean;
  msg: { text: string; tone: "ok" | "warn" } | null;
  loadedAt: string;
}>();

const emit = defineEmits<{ refresh: []; collect: [] }>();

/* ---- 展示辅助（纯格式化，不做语义决策）---- */

const numFmt = new Intl.NumberFormat("zh-CN");

function fmtNum(n: number): string {
  return numFmt.format(n);
}

function fmtRate(n: number): string {
  return Number.isInteger(n) ? fmtNum(n) : n.toFixed(1);
}

function ratioOf(p: PackageRow): number | null {
  return p.total > 0 ? Math.min(Math.max(p.remaining / p.total, 0), 1) : null;
}

function forecastLine(row: RadarRow, packageId: string): string | null {
  const f = row.forecasts.find((x) => x.package_id === packageId);
  if (!f) return null;
  if (f.exhausted_on) return `预计 ${f.exhausted_on} 耗尽 · 约 ${fmtRate(f.per_day)} ${f.unit}/天`;
  if (f.days_left !== null) {
    return `约 ${fmtRate(f.days_left)} 天后耗尽 · ${fmtRate(f.per_day)} ${f.unit}/天`;
  }
  return "暂无耗尽预测";
}

function aggText(s: { [key: string]: unknown }): string {
  return JSON.stringify(s, null, 2);
}
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">用量管理</h1>
        <p class="page-sub">各家账户余额、额度流水与耗尽预测。</p>
      </div>
      <div class="head-actions">
        <span v-if="loadedAt" class="row-time">更新于 {{ loadedAt }}</span>
        <button class="btn" :disabled="loading || collecting" @click="emit('refresh')">刷新</button>
        <button class="btn btn--primary" :disabled="loading || collecting" @click="emit('collect')">
          {{ collecting ? "采集中…" : "立即采集" }}
        </button>
      </div>
    </div>
  </header>

  <p
    v-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <div class="wall">
    <article v-for="row in rows" :key="row.account_id" class="acct sheet">
      <header class="acct-head">
        <PlatformBadge :name="row.account_name" :color-index="faceOf(row.account_id)" />
        <span class="acct-id mono">{{ row.account_id }}</span>
      </header>
      <div class="acct-body">
        <p class="row-sub">
          {{ row.platform_code || "vault-only" }}
          <template v-if="row.collected_at"> · 采集于 {{ fmtTime(row.collected_at) }}</template>
          <template v-else> · 尚未采集</template>
        </p>

        <p v-if="!row.packages.length && !row.recent_ledger.length" class="quietline">
          暂无用量数据——点上方「立即采集」。
        </p>

        <div v-if="row.packages.some((p) => p.remaining > 0)" class="pkgs">
          <template v-for="p in row.packages" :key="p.package_id">
            <section v-if="p.remaining > 0" class="pkg">
              <p class="pkg-name">
                {{ p.name }}
                <span v-if="row.quota_low.includes(p.name)" class="tag tag--attention">低额</span>
              </p>
              <p class="pkg-balance">
                <span class="pkg-remaining num">{{ fmtNum(p.remaining) }}</span>
                <span class="pkg-unit num">/ {{ fmtNum(p.total) }} {{ p.unit }}</span>
              </p>
              <div
                v-if="ratioOf(p) !== null"
                class="bar"
                role="img"
                :aria-label="`余额 ${p.remaining} / ${p.total} ${p.unit}`"
              >
                <div
                  class="bar-fill"
                  :style="{ width: `${((ratioOf(p) ?? 0) * 100).toFixed(1)}%` }"
                ></div>
              </div>
              <p class="row-sub">
                已用 {{ fmtNum(p.used) }}
                <template v-if="p.cycle_end"> · 周期至 {{ fmtTime(p.cycle_end) }}</template>
                <template v-if="p.status"> · 状态 {{ p.status }}</template>
              </p>
              <p v-if="forecastLine(row, p.package_id)" class="pkg-forecast">
                {{ forecastLine(row, p.package_id) }}
              </p>
              <p v-else class="pkg-forecast pkg-forecast--quiet">采集中——再采一帧即出耗尽预测。</p>
            </section>
          </template>
        </div>

        <!-- 历史耗尽包（remaining=0 的领取/活动包）折叠收纳：数据如实全保留，默认不喧哗 -->
        <details v-if="row.packages.some((p) => p.remaining <= 0)" class="fold history-fold">
          <summary>
            已耗尽的历史包（{{ row.packages.filter((p) => p.remaining <= 0).length }} 个）
          </summary>
          <ul class="rows history-rows">
            <li
              v-for="p in row.packages.filter((p) => p.remaining <= 0)"
              :key="p.package_id"
              class="row"
            >
              <span class="row-main">
                <p class="row-title">{{ p.name }}</p>
                <p v-if="p.cycle_end" class="row-sub">周期至 {{ fmtTime(p.cycle_end) }}</p>
              </span>
              <span class="row-sub num">0 / {{ fmtNum(p.total) }} {{ p.unit }}</span>
            </li>
          </ul>
        </details>

        <details v-if="row.aggregate_summary" class="fold agg-fold">
          <summary>用量汇总原话 · {{ fmtTime(row.aggregate_collected_at) }}</summary>
          <pre class="agg-raw mono">{{ aggText(row.aggregate_summary) }}</pre>
        </details>

        <div v-if="row.recent_ledger.length" class="ledger">
          <p class="ledger-title">最近流水</p>
          <ul class="rows">
            <li v-for="e in row.recent_ledger" :key="e.record_id" class="row">
              <span class="ledger-amount num">{{ fmtNum(e.amount) }} {{ e.unit }}</span>
              <span class="row-main">
                <p class="row-title">{{ e.kind }}</p>
                <p class="row-sub mono">{{ e.record_id }}</p>
              </span>
              <span class="row-time">{{ fmtTime(e.occurred_at) }}</span>
            </li>
          </ul>
        </div>
      </div>
    </article>
    <article v-if="!rows.length" class="acct acct--empty sheet">
      <p class="quietline">
        还没有可观测的账户——先到「平台管理」页导入，或点上方「立即采集」。
      </p>
    </article>
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
.head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.wall {
  margin-top: var(--space-6);
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: var(--space-5);
}

.acct-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}
/* 无数据时的占位卡：整行铺满，保留「这里本该有卡片」的版面感 */
.acct--empty {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 110px;
  border: 1px dashed var(--color-border);
}
.acct-id { margin: 0; font-size: var(--text-xs); color: var(--color-text-faint); }
.acct-body { padding: var(--space-4) var(--space-5); }

.pkgs {
  margin-top: var(--space-3);
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--color-border);
}
.pkg {
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--color-border);
}
.pkg-name {
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}
.pkg-balance { margin: var(--space-1) 0 0; }
.pkg-remaining {
  font-size: var(--text-2xl);
  font-weight: 650;
  letter-spacing: -0.01em;
}
.pkg-unit {
  margin-left: var(--space-1);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}
.bar {
  margin-top: var(--space-2);
  height: 6px;
  border-radius: 3px;
  background: var(--color-surface-2);
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--color-ink);
  transition: width var(--motion-base) var(--ease-out);
}
.pkg-forecast {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
  color: var(--color-accent);
}
.pkg-forecast--quiet { color: var(--color-text-faint); }

.agg-fold { margin-top: var(--space-3); }
.agg-raw {
  margin: var(--space-2) 0 0;
  padding: var(--space-3);
  background: var(--color-bg);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  line-height: 1.5;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.ledger { margin-top: var(--space-4); }
.ledger-title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}
.ledger-amount {
  min-width: 90px;
  text-align: right;
  white-space: nowrap;
}
</style>
