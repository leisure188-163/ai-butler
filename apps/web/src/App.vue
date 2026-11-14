<script setup lang="ts">
/**
 * Butler 管理台 · 应用壳（A3-01 四页 IA，矩阵即首页）
 *
 * 壳 = 装配器（conventions/04 §2.4，业务子域分包 2026-11-14；对齐 api.py 纯聚合器纪律）：
 * 只组装各域 composable 与轮询 wiring，不持业务逻辑——
 * 路由域 useHashRoute / 数据源域 useShellData / 账号域动作 useAccountActions /
 * 用量域动作 useUsageActions / 设置域 useSettings；端点访问单源 api.ts。
 *
 * 渲染纪律（A3-01，红线 2）：状态染色只消费 core 出产的 signal 分类
 * （ok/notice/attention/danger/quiet），不认识 Status / HealthLevel 字面量本身；
 * repair_hint / evidence 是 core 产文案，直渲染不加工；页面状态走 hash（可直链可后退）。
 */
import { onBeforeUnmount, onMounted, watch } from "vue";
import SideNav from "./components/SideNav.vue";
import AccountsPage from "./pages/AccountsPage.vue";
import UsagePage from "./pages/UsagePage.vue";
import LogPage from "./pages/LogPage.vue";
import SettingsPage from "./pages/SettingsPage.vue";
import { useHashRoute } from "./composables/useHashRoute";
import { useShellData } from "./composables/useShellData";
import { useAccountActions } from "./composables/useAccountActions";
import { useUsageActions } from "./composables/useUsageActions";
import { useSettings } from "./composables/useSettings";

/* ---- 装配（各域 composable；解构保模板绑定名，template 零变化）---- */
const { active, navigate } = useHashRoute();
const data = useShellData();
const account = useAccountActions({ refresh: data.loadAll });
const usage = useUsageActions({ refresh: data.loadAll, radarRows: data.radarRows });
const { settings, updateSettings } = useSettings();

const {
  accounts,
  apps,
  runs,
  pending,
  radarRows,
  loading,
  loadError,
  loadedAt,
  usageLoadedAt,
  serverInfo,
  todayDone,
  alertCount,
  loadAll,
} = data;
const {
  busyTarget,
  actionMsg,
  importApp,
  claimApp,
  healthApp,
  importAllApps,
  claimAllApps,
  claimMany,
} = account;
const { collecting, usageMsg, collectUsage } = usage;

/* ---- 轮询 wiring（settings × loadAll 交叉依赖，留壳不硬塞进任何域）---- */
let pollTimer: number | undefined;

function schedulePoll() {
  if (pollTimer !== undefined) window.clearInterval(pollTimer);
  pollTimer = undefined;
  if (settings.value.autoRefresh) {
    pollTimer = window.setInterval(loadAll, settings.value.intervalSec * 1000);
  }
}

watch(() => [settings.value.autoRefresh, settings.value.intervalSec], schedulePoll);

onMounted(() => {
  loadAll();
  schedulePoll();
});

onBeforeUnmount(() => {
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
