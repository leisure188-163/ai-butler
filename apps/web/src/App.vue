<script setup lang="ts">
/**
 * Kabao 管理台 · 应用壳（A3-01 矩阵改版：四页 IA = 账号/用量/记录/设置，矩阵即首页）
 *
 * 渲染纪律（A3-01，红线 2）：
 * - 状态染色只消费 core 出产的 signal 分类（ok/notice/attention/danger/quiet），
 *   不认识 Status / HealthLevel 字面量本身；status 仅在结果列如实展示原文
 * - repair_hint / evidence 是 core 产文案，直渲染不加工
 * - 页面拆在 pages/，本壳只持数据、轮询与动作；页面状态走 hash（可直链可后退）；
 *   旧直链（#/home、#/wallet、#/card、#/alerts、#/radar）静默重定向到规范 hash
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import SideNav from "./components/SideNav.vue";
import AccountsPage from "./pages/AccountsPage.vue";
import UsagePage from "./pages/UsagePage.vue";
import LogPage from "./pages/LogPage.vue";
import SettingsPage from "./pages/SettingsPage.vue";
import type {
  AccountItem,
  AppItem,
  CollectOutcome,
  ImportResult,
  PageName,
  RadarRow,
  RunItem,
  Settings,
  ThemeName,
} from "./types";
import { isToday } from "./utils";

const apiBase = "/api/v1";

const hashByPage: Record<PageName, string> = {
  账号: "accounts",
  用量: "usage",
  记录: "log",
  设置: "settings",
};
/* 旧直链兼容（矩阵改版）：别名命中即 replaceState 重写为规范 hash */
const legacyHashByPage: Record<string, PageName> = {
  home: "账号",
  wallet: "账号",
  card: "账号",
  alerts: "账号",
  radar: "用量",
};
const pageByHash = {
  ...Object.fromEntries(Object.entries(hashByPage).map(([page, hash]) => [hash, page])),
  ...legacyHashByPage,
} as Record<string, PageName>;

function resolveActive(): PageName {
  const hash = location.hash.slice(2);
  const page = pageByHash[hash] ?? "账号";
  if (pageByHash[hash] && hash !== hashByPage[page]) {
    history.replaceState(null, "", `#/${hashByPage[page]}`);
  }
  return page;
}

const active = ref<PageName>(resolveActive());

function onHashChange() {
  const page = pageByHash[location.hash.slice(2)];
  if (page) active.value = page;
}

function navigate(page: PageName) {
  if (location.hash !== `#/${hashByPage[page]}`) location.hash = `#/${hashByPage[page]}`;
  active.value = page;
}

const accounts = ref<AccountItem[]>([]);
const apps = ref<AppItem[]>([]);
const runs = ref<RunItem[]>([]);
const pending = ref<RunItem[]>([]);
const loading = ref(false);
const loadError = ref("");
const loadedAt = ref("");
const busyTarget = ref<string | null>(null);
const actionMsg = ref<{ text: string; tone: "ok" | "warn" } | null>(null);
const serverInfo = ref<{ title: string; version: string } | null>(null);
/* 用量数据上收壳（矩阵额度列与用量页共用；radar 拉取失败静默为 []，不阻塞主数据） */
const radarRows = ref<RadarRow[]>([]);
const collecting = ref(false);
const usageLoadedAt = ref("");
const usageMsg = ref<{ text: string; tone: "ok" | "warn" } | null>(null);

async function loadAll() {
  loading.value = true;
  loadError.value = "";
  try {
    const [acc, run, pend, appList, radar] = await Promise.all([
      fetch(`${apiBase}/accounts`),
      fetch(`${apiBase}/runs?limit=50`),
      fetch(`${apiBase}/pending?limit=20`),
      fetch(`${apiBase}/apps`),
      /* radar 独立容错：失败静默为 []（矩阵额度列显示「—」），不拖垮主数据 */
      fetch(`${apiBase}/usage/radar`)
        .then((r) => (r.ok ? (r.json() as Promise<RadarRow[]>) : []))
        .catch(() => [] as RadarRow[]),
    ]);
    if (!acc.ok || !run.ok || !pend.ok || !appList.ok) {
      throw new Error(`HTTP ${acc.status}/${run.status}/${pend.status}/${appList.status}`);
    }
    accounts.value = (await acc.json()) as AccountItem[];
    runs.value = (await run.json()) as RunItem[];
    pending.value = (await pend.json()) as RunItem[];
    apps.value = (await appList.json()) as AppItem[];
    radarRows.value = radar;
    loadedAt.value = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date());
    usageLoadedAt.value = loadedAt.value;
  } catch {
    loadError.value = "够不到本机服务（server 未启动？）——启动后到侧栏点刷新。";
  } finally {
    loading.value = false;
  }
  void fetchServerInfo();
}

/* 版本信息纯展示，任何失败都静默（dev 代理可能不转发 /openapi.json） */
async function fetchServerInfo() {
  try {
    const resp = await fetch("/openapi.json");
    if (!resp.ok) return;
    const info = (await resp.json()) as { info?: { title?: string; version?: string } };
    if (info.info?.title && info.info.version) {
      serverInfo.value = { title: info.info.title, version: info.info.version };
    }
  } catch {
    /* 忽略 */
  }
}

/* 应用动作：导入（本机接入扫描）/ 领取（手动领取）。结果如实展示，不造结论。 */
async function importApp(target: string) {
  busyTarget.value = target;
  actionMsg.value = null;
  try {
    const resp = await fetch(`${apiBase}/apps/${target}/import`, { method: "POST" });
    const body = (await resp.json()) as { accounts?: string[]; issues?: string[]; detail?: string };
    if (!resp.ok) {
      actionMsg.value = { text: body.detail ?? `导入失败（HTTP ${resp.status}）`, tone: "warn" };
      return;
    }
    const issues = body.issues ?? [];
    const imported = body.accounts ?? [];
    actionMsg.value = {
      text: imported.length
        ? `已导入：${imported.join("、")}` + (issues.length ? ` · ${issues.join("；")}` : "")
        : issues.length
          ? issues.join("；")
          : "没有发现可导入的卡。",
      tone: imported.length ? "ok" : "warn",
    };
  } finally {
    busyTarget.value = null;
    await loadAll();
  }
}

async function claimApp(target: string) {
  busyTarget.value = target;
  actionMsg.value = null;
  try {
    const resp = await fetch(`${apiBase}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target }),
    });
    const body = (await resp.json()) as {
      status?: string | null;
      repair_reason?: string | null;
      detail?: string;
    };
    if (!resp.ok) {
      actionMsg.value = { text: body.detail ?? `领取失败（HTTP ${resp.status}）`, tone: "warn" };
      return;
    }
    actionMsg.value = {
      text:
        body.status === "CLAIMED" || body.status === "ALREADY"
          ? `本轮领取完成（${body.status}）`
          : `领取未完成：${body.status ?? "未终态"}` +
            (body.repair_reason ? ` —— ${body.repair_reason}` : ""),
      tone: body.status === "CLAIMED" || body.status === "ALREADY" ? "ok" : "warn",
    };
  } finally {
    busyTarget.value = null;
    await loadAll();
  }
}

/* 体检探针（R3 网页通道）：kind=health.check 走同一 /runs 通道，结论如实转述 */
async function healthApp(target: string) {
  busyTarget.value = target;
  actionMsg.value = null;
  try {
    const resp = await fetch(`${apiBase}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, kind: "health.check" }),
    });
    const body = (await resp.json()) as {
      status?: string | null;
      repair_reason?: string | null;
      detail?: string;
    };
    if (!resp.ok) {
      actionMsg.value = { text: body.detail ?? `体检失败（HTTP ${resp.status}）`, tone: "warn" };
      return;
    }
    const ok = body.status === "ALREADY";
    actionMsg.value = {
      text: ok
        ? "体检通过：会话有效"
        : `体检结论：${body.status ?? "未终态"}` +
          (body.repair_reason ? ` —— ${body.repair_reason}` : ""),
      tone: ok ? "ok" : "warn",
    };
  } finally {
    busyTarget.value = null;
    await loadAll();
  }
}

/* 一键批量（R2 补）：导入全部未泊位 / 领取全部已泊位——选卡语义在 server，端只发起与转述 */
async function importAllApps() {
  busyTarget.value = "batch";
  actionMsg.value = { text: "正在扫描本机客户端…", tone: "ok" };
  try {
    const resp = await fetch(`${apiBase}/apps/import-all`, { method: "POST" });
    const body = (await resp.json()) as ImportResult[] | { detail?: string };
    if (!resp.ok) {
      actionMsg.value = {
        text: (body as { detail?: string }).detail ?? `一键导入失败（HTTP ${resp.status}）`,
        tone: "warn",
      };
      return;
    }
    const results = body as ImportResult[];
    const imported = results.flatMap((r) => r.accounts);
    const issues = results.flatMap((r) => r.issues.map((i) => `${r.target}：${i}`));
    const empty = results
      .filter((r) => !r.accounts.length && !r.issues.length)
      .map((r) => r.target);
    const text =
      [
        imported.length ? `已导入：${imported.join("、")}` : "",
        empty.length ? `未发现卡：${empty.join("、")}` : "",
        ...issues,
      ]
        .filter(Boolean)
        .join(" · ") || "没有待导入的应用。";
    actionMsg.value = { text, tone: issues.length ? "warn" : "ok" };
  } finally {
    busyTarget.value = null;
    await loadAll();
  }
}

async function claimAllApps() {
  busyTarget.value = "batch";
  actionMsg.value = { text: "正在逐张领取…", tone: "ok" };
  try {
    const resp = await fetch(`${apiBase}/runs/claim-all`, { method: "POST" });
    const body = (await resp.json()) as RunItem[] | { detail?: string };
    if (!resp.ok) {
      actionMsg.value = {
        text: (body as { detail?: string }).detail ?? `一键领取失败（HTTP ${resp.status}）`,
        tone: "warn",
      };
      return;
    }
    const rows = body as RunItem[];
    const done = rows.filter((r) => r.signal === "ok").length;
    const rest = rows
      .filter((r) => r.signal !== "ok")
      .map(
        (r) =>
          `${r.target}：${r.status ?? "未终态"}${r.repair_reason ? `（${r.repair_reason}）` : ""}`,
      );
    const text = rows.length
      ? `共发起 ${rows.length} 张，完成 ${done} 张` + (rest.length ? ` · ${rest.join(" · ")}` : "")
      : "还没有已泊位的卡——先导入应用。";
    actionMsg.value = { text, tone: rest.length ? "warn" : "ok" };
  } finally {
    busyTarget.value = null;
    await loadAll();
  }
}

/* 勾选批量领取（矩阵页）：逐个顺序执行（与 claim 单发同语义），结果如实逐条转述 */
async function claimMany(targets: string[]) {
  if (!targets.length) return;
  busyTarget.value = "batch";
  actionMsg.value = null;
  const lines: string[] = [];
  const statuses: (string | null)[] = [];
  try {
    for (const target of targets) {
      try {
        const resp = await fetch(`${apiBase}/runs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target }),
        });
        const body = (await resp.json()) as {
          status?: string | null;
          repair_reason?: string | null;
          detail?: string;
        };
        if (!resp.ok) {
          lines.push(`${target}：${body.detail ?? `HTTP ${resp.status}`}`);
          statuses.push(null);
          continue;
        }
        statuses.push(body.status ?? null);
        lines.push(
          `${target}：${body.status ?? "未终态"}` +
            (body.repair_reason ? `（${body.repair_reason}）` : ""),
        );
      } catch {
        lines.push(`${target}：请求失败`);
        statuses.push(null);
      }
    }
    const done = statuses.every((s) => s === "CLAIMED" || s === "ALREADY");
    actionMsg.value = { text: lines.join(" · "), tone: done ? "ok" : "warn" };
  } finally {
    busyTarget.value = null;
    await loadAll();
  }
}

/* 用量采集（用量页「立即采集」）：结果如实分列，不造总结论（原额度雷达页逻辑上收） */
async function collectUsage() {
  collecting.value = true;
  usageMsg.value = null;
  try {
    const resp = await fetch(`${apiBase}/usage/collect`, { method: "POST" });
    const body = (await resp.json()) as CollectOutcome[] | { detail?: string };
    if (!resp.ok) {
      usageMsg.value = {
        text: (body as { detail?: string }).detail ?? `采集失败（HTTP ${resp.status}）`,
        tone: "warn",
      };
      return;
    }
    if (!Array.isArray(body)) {
      usageMsg.value = { text: "采集响应形状异常（预期结果列表）", tone: "warn" };
      return;
    }
    usageMsg.value = {
      text: summarizeCollect(body),
      tone: body.some((o) => o.error) ? "warn" : "ok",
    };
  } catch {
    usageMsg.value = { text: "采集失败——够不到本机服务。", tone: "warn" };
  } finally {
    collecting.value = false;
    await loadAll();
  }
}

function summarizeCollect(outcomes: CollectOutcome[]): string {
  if (!outcomes.length) return "没有可采集的账号——先到「账号」页导入应用。";
  return outcomes
    .map((o) => {
      const name =
        radarRows.value.find((r) => r.account_id === o.account_id)?.display_name ?? o.account_id;
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

/* 设置：本机浏览器持久化 + 自动刷新轮询。
   注意：THEME_NAMES 必须先于 loadSettings() 调用点声明（函数声明提升、const 不提升，
   否则 has() 进 TDZ 抛错被 try/catch 静默吞掉，存档主题永远回退 system）。 */
const THEME_NAMES: ReadonlySet<string> = new Set(["system", "paper", "dark", "warm"]);

const settings = ref<Settings>(loadSettings());

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem("kabao.settings.v1");
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Settings>;
      return {
        autoRefresh: parsed.autoRefresh ?? true,
        intervalSec: parsed.intervalSec ?? 60,
        theme: parsed.theme && THEME_NAMES.has(parsed.theme) ? parsed.theme : "system",
      };
    }
  } catch {
    /* 存档损坏即回默认 */
  }
  return { autoRefresh: true, intervalSec: 60, theme: "system" };
}

function updateSettings(patch: Partial<Settings>) {
  settings.value = { ...settings.value, ...patch };
  localStorage.setItem("kabao.settings.v1", JSON.stringify(settings.value));
}

/* 主题：跟随系统（prefers-color-scheme 实时跟随）或指定主题；<html data-theme> 上屏 */
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

function applyTheme() {
  const pref = settings.value.theme;
  const resolved: Exclude<ThemeName, "system"> =
    pref === "system" ? (systemDark.matches ? "dark" : "paper") : pref;
  if (resolved === "paper") {
    delete document.documentElement.dataset.theme; /* :root 即卡纸与墨 */
  } else {
    document.documentElement.dataset.theme = resolved;
  }
}

applyTheme();
systemDark.addEventListener("change", applyTheme);
watch(() => settings.value.theme, applyTheme);

let pollTimer: number | undefined;

function schedulePoll() {
  if (pollTimer !== undefined) window.clearInterval(pollTimer);
  pollTimer = undefined;
  if (settings.value.autoRefresh) {
    pollTimer = window.setInterval(loadAll, settings.value.intervalSec * 1000);
  }
}

watch(() => [settings.value.autoRefresh, settings.value.intervalSec], schedulePoll);

/* 今日自动巡检一句话（待办栏/矩阵页头用）：体检类 runs 按本地自然日聚合 */
const todayDone = computed(() => {
  const today = runs.value.filter((r) => r.kind === "health.check" && isToday(r.started_at));
  if (!today.length) return null;
  return {
    label: "自动巡检",
    ok: today.filter((r) => r.signal === "ok").length,
    total: today.length,
  };
});

/* 提醒角标 = 待处理 + 非正常卡 + 即将到期凭据（条目数，不去重） */
const alertCount = computed(
  () =>
    pending.value.length +
    accounts.value.filter((a) => a.signal !== "ok").length +
    accounts.value.reduce(
      (n, a) => n + a.credentials.filter((c) => c.signal === "notice").length,
      0,
    ),
);

onMounted(() => {
  if (!location.hash) history.replaceState(null, "", `#/${hashByPage[active.value]}`);
  window.addEventListener("hashchange", onHashChange);
  loadAll();
  schedulePoll();
});

onBeforeUnmount(() => {
  window.removeEventListener("hashchange", onHashChange);
  systemDark.removeEventListener("change", applyTheme);
  if (pollTimer !== undefined) window.clearInterval(pollTimer);
});
</script>

<template>
  <div class="shell">
    <SideNav
      :active="active"
      :alert-count="alertCount"
      :loading="loading"
      :loaded-at="loadedAt"
      @navigate="navigate"
      @refresh="loadAll"
    />

    <main class="content">
      <p v-if="loadError" class="errorline" role="alert">{{ loadError }}</p>

      <AccountsPage
        v-if="active === '账号'"
        :accounts="accounts"
        :apps="apps"
        :radar="radarRows"
        :pending="pending"
        :runs="runs"
        :busy-target="busyTarget"
        :msg="actionMsg"
        :loading="loading"
        :load-error="loadError"
        :today-done="todayDone"
        @import="importApp"
        @claim="claimApp"
        @health="healthApp"
        @claim-many="claimMany"
        @import-all="importAllApps"
        @claim-all="claimAllApps"
      />
      <UsagePage
        v-else-if="active === '用量'"
        :rows="radarRows"
        :loading="loading"
        :collecting="collecting"
        :msg="usageMsg"
        :loaded-at="usageLoadedAt"
        @refresh="loadAll"
        @collect="collectUsage"
      />
      <LogPage v-else-if="active === '记录'" :runs="runs" />
      <SettingsPage
        v-else
        :settings="settings"
        :server-info="serverInfo"
        @update="updateSettings"
      />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
}
.content {
  flex: 1;
  min-width: 0;
  max-width: 1160px;
  padding: var(--space-8);
  box-sizing: border-box;
}

/* 与 SideNav 的 900px 断点配套：侧栏变顶部横条，壳随之转纵向，否则 main 被挤出屏 */
@media (max-width: 900px) {
  .shell { flex-direction: column; }
}

@media (max-width: 640px) {
  .content { padding: var(--space-5) var(--space-4) var(--space-8); }
}
</style>
