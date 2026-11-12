<script setup lang="ts">
/**
 * 额度雷达（R2-E）：各家套餐余额 + 用量流水 + 耗尽预测，一页看全。
 *
 * 渲染纪律（红线 2）：余额/预测/流水都是 server 投影的 core 出产数据，
 * 页面不做语义加工——forecast 缺失（不足两帧差分）如实显示「采集中」；
 * quota_low 是 core 谓词（is_quota_low）出产的包名列表，只做布尔标记；
 * aggregate_summary 是连接器原话，折叠直渲染不重排。
 * 数据自持：GET /usage/radar + 手动 POST /usage/collect，不搭 App 轮询便车。
 */
import { onMounted, ref } from "vue";
import type { CollectOutcome, PackageRow, RadarRow } from "../types";
import { faceOf, fmtTime } from "../utils";

const apiBase = "/api/v1";

const rows = ref<RadarRow[]>([]);
const loading = ref(false);
const loadError = ref("");
const loadedAt = ref("");
const collecting = ref(false);
const msg = ref<{ text: string; tone: "ok" | "warn" } | null>(null);

async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    const resp = await fetch(`${apiBase}/usage/radar`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    rows.value = (await resp.json()) as RadarRow[];
    loadedAt.value = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date());
  } catch {
    loadError.value = "够不到本机服务（server 未启动？）——启动后点刷新。";
  } finally {
    loading.value = false;
  }
}

/* 采集全账号：结果如实分列（saved 条数 / 低额包 / error），不造总结论 */
async function collect() {
  collecting.value = true;
  msg.value = null;
  try {
    const resp = await fetch(`${apiBase}/usage/collect`, { method: "POST" });
    const body = (await resp.json()) as CollectOutcome[] | { detail?: string };
    if (!resp.ok) {
      const detail = "detail" in body && body.detail ? body.detail : `HTTP ${resp.status}`;
      msg.value = { text: `采集失败（${detail}）`, tone: "warn" };
      return;
    }
    if (!Array.isArray(body)) {
      msg.value = { text: "采集响应形状异常（预期结果列表）", tone: "warn" };
      return;
    }
    msg.value = { text: summarize(body), tone: body.some((o) => o.error) ? "warn" : "ok" };
  } catch {
    msg.value = { text: "采集失败——够不到本机服务。", tone: "warn" };
  } finally {
    collecting.value = false;
    await load();
  }
}

function summarize(outcomes: CollectOutcome[]): string {
  if (!outcomes.length) return "没有可采集的账号——先到「卡包」导入应用。";
  return outcomes
    .map((o) => {
      const name =
        rows.value.find((r) => r.account_id === o.account_id)?.display_name ?? o.account_id;
      if (o.error) return `${name}：${o.error}`;
      const saved = [
        o.snapshot_saved ? "余额" : "",
        o.aggregate_saved ? "汇总" : "",
        o.ledger_saved > 0 ? `流水×${o.ledger_saved}` : "",
      ]
        .filter(Boolean)
        .join("·");
      const low = o.quota_low.length ? `；低额：${o.quota_low.join("、")}` : "";
      return `${name}：${saved || "无新数据"}${low}`;
    })
    .join("；");
}

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

onMounted(load);
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">额度雷达</h1>
        <p class="page-sub">各家套餐余额、用量流水与耗尽预测（相邻两帧差分）。</p>
      </div>
      <div class="head-actions">
        <span v-if="loadedAt" class="row-time">更新于 {{ loadedAt }}</span>
        <button class="btn" :disabled="loading || collecting" @click="load">刷新</button>
        <button class="btn btn--primary" :disabled="loading || collecting" @click="collect">
          {{ collecting ? "采集中…" : "立即采集" }}
        </button>
      </div>
    </div>
  </header>

  <p v-if="loadError" class="errorline" role="alert">{{ loadError }}</p>
  <p
    v-else-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <div v-if="rows.length" class="wall">
    <article v-for="row in rows" :key="row.account_id" class="acct sheet">
      <header class="acct-banner" :class="`acct-banner--${faceOf(row.account_id)}`">
        <p class="acct-name">{{ row.display_name }}</p>
        <p class="acct-id mono">{{ row.account_id }}</p>
      </header>
      <div class="acct-body">
        <p class="row-sub">
          {{ row.provider || "vault-only" }}
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
              <span v-if="row.quota_low.includes(p.name)" class="stamp stamp--attention">低额</span>
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

      <!-- 历史耗尽包（remaining=0 的签到/裂变包）折叠收纳：数据如实全保留，默认不喧哗 -->
      <details
        v-if="row.packages.some((p) => p.remaining <= 0)"
        class="fold history-fold"
      >
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
          <li
            v-for="e in row.recent_ledger" :key="e.record_id" class="row"
          >
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
  </div>
  <p v-else-if="!loading && !loadError" class="quietline">
    还没有可观测的账号——先到「卡包」导入应用。
  </p>
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
.acct { overflow: hidden; }

/* face 色节头横幅：卡面身份色 straight 取用，白字沿用卡面锚定 token */
.acct-banner {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  color: var(--face-text);
}
.acct-banner--1 { background: var(--card-face-1); }
.acct-banner--2 { background: var(--card-face-2); }
.acct-banner--3 { background: var(--card-face-3); }
.acct-banner--4 { background: var(--card-face-4); }
.acct-banner--5 { background: var(--card-face-5); }
.acct-banner--6 { background: var(--card-face-6); }
.acct-name { margin: 0; font-size: var(--text-lg); font-weight: 650; }
.acct-id { margin: 0; font-size: var(--text-xs); opacity: 0.8; }
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

.ledger { margin-top: var(--space-4); }.ledger-title {
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
