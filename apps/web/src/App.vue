<script setup lang="ts">
/**
 * Kabao 管理台 · 应用壳（A3-01：侧边栏 IA，总览 = 首页/卡包/记录；管理 = 提醒/设置）
 *
 * 渲染纪律（A3-01，红线 2）：
 * - 状态染色只消费 core 出产的 signal 分类（ok/notice/attention/danger/quiet），
 *   不认识 Status / HealthLevel 字面量本身；status 仅在结果列如实展示原文
 * - repair_hint / evidence 是 core 产文案，直渲染不加工
 * - 页面拆在 pages/，本壳只持数据、轮询与动作；页面状态走 hash（可直链可后退）
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import SideNav from "./components/SideNav.vue";
import HomePage from "./pages/HomePage.vue";
import WalletPage from "./pages/WalletPage.vue";
import LogPage from "./pages/LogPage.vue";
import AlertsPage from "./pages/AlertsPage.vue";
import SettingsPage from "./pages/SettingsPage.vue";
import type { AccountItem, AppItem, PageName, RunItem, Settings, ThemeName } from "./types";

const apiBase = "/api/v1";

const hashByPage: Record<PageName, string> = {
  首页: "home",
  卡包: "wallet",
  记录: "log",
  提醒: "alerts",
  设置: "settings",
};
const pageByHash = Object.fromEntries(
  Object.entries(hashByPage).map(([page, hash]) => [hash, page]),
) as Record<string, PageName>;

const active = ref<PageName>(pageByHash[location.hash.slice(2)] ?? "首页");

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

async function loadAll() {
  loading.value = true;
  loadError.value = "";
  try {
    const [acc, run, pend, appList] = await Promise.all([
      fetch(`${apiBase}/accounts`),
      fetch(`${apiBase}/runs?limit=50`),
      fetch(`${apiBase}/pending?limit=20`),
      fetch(`${apiBase}/apps`),
    ]);
    if (!acc.ok || !run.ok || !pend.ok || !appList.ok) {
      throw new Error(`HTTP ${acc.status}/${run.status}/${pend.status}/${appList.status}`);
    }
    accounts.value = (await acc.json()) as AccountItem[];
    runs.value = (await run.json()) as RunItem[];
    pending.value = (await pend.json()) as RunItem[];
    apps.value = (await appList.json()) as AppItem[];
    loadedAt.value = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date());
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

      <HomePage
        v-if="active === '首页'"
        :accounts="accounts"
        :apps="apps"
        :pending="pending"
        :loading="loading"
        :load-error="loadError"
        @navigate="navigate"
      />
      <WalletPage
        v-else-if="active === '卡包'"
        :apps="apps"
        :accounts="accounts"
        :busy-target="busyTarget"
        :msg="actionMsg"
        @import="importApp"
        @claim="claimApp"
      />
      <LogPage v-else-if="active === '记录'" :runs="runs" />
      <AlertsPage
        v-else-if="active === '提醒'"
        :pending="pending"
        :accounts="accounts"
        @navigate="navigate"
      />
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
