<script setup lang="ts">
/**
 * Butler 管理台 · 应用壳（ADR-010 六页 IA，仪表盘默认）
 *
 * 壳 = 装配器（conventions/4 §2.4，业务子域分包 2026-11-14；对齐 api.py 纯聚合器纪律）：
 * 只组装各域 composable 与轮询 wiring，不持业务逻辑——
 * 路由域 useHashRoute / 数据源域 useShellData / 账户域动作 useAccountActions /
 * 流量域动作 useUsageActions / 设置域 useSettings；端点访问单源 api.ts。
 *
 * 渲染纪律（A3-01 v2，红线 2）：状态染色只消费 core 出产的 signal 分类
 * （ok/notice/attention/danger/quiet），不认识 Status / HealthLevel 字面量本身；
 * repair_hint / evidence 是 core 产文案，直渲染不加工；页面状态走 hash（可直链可后退）。
 */
import { computed, onBeforeUnmount, onMounted, watch } from "vue";
import SideNav from "./components/SideNav.vue";
import DashboardPage from "./pages/DashboardPage.vue";
import AppsPage from "./pages/AppsPage.vue";
import AccountsPage from "./pages/AccountsPage.vue";
import TrafficPage from "./pages/TrafficPage.vue";
import LogPage from "./pages/LogPage.vue";
import SettingsPage from "./pages/SettingsPage.vue";
import { useHashRoute } from "./composables/useHashRoute";
import { useShellData } from "./composables/useShellData";
import { useAccountActions } from "./composables/useAccountActions";
import { useUsageActions } from "./composables/useUsageActions";
import { useSettings } from "./composables/useSettings";
import { useGatewayRoutes } from "./composables/useGatewayRoutes";

/* ---- 装配（各域 composable；解构保模板绑定名）---- */
const { active, navigate } = useHashRoute();
const data = useShellData();
const account = useAccountActions({ refresh: data.loadAll });
const usage = useUsageActions({ refresh: data.loadAll, radarRows: data.radarRows });
const { settings, updateSettings } = useSettings();
const {
  routes: gatewayRoutes,
  takesEffect,
  loadingRoutes,
  savingRoutes,
  routesMsg,
  loadRoutes,
  saveRoutes,
} = useGatewayRoutes();

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

/* 待办栏可领取 target 集合（纯派生：申报了 provision.run 且已导入的应用） */
const claimable = computed(
  () =>
    new Set(
      apps.value
        .filter((a) => a.account_id && a.capabilities.includes("provision.run"))
        .map((a) => a.id),
    ),
);

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
  if (active.value === "设置") loadRoutes();
});

/* 进设置页时装载路由表（设置页局部数据不进轮询，R4-G6） */
watch(active, (page) => {
  if (page === "设置") loadRoutes();
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

      <AppsPage
        v-if="active === '应用'"
        :apps="apps"
        :accounts="accounts"
        :busy-target="busyTarget"
        :msg="actionMsg"
        :loading="loading"
        :load-error="loadError"
        @import="importApp"
        @import-all="importAllApps"
        @jump="navigate"
      />
      <AccountsPage
        v-else-if="active === '账户'"
        :accounts="accounts"
        :apps="apps"
        :radar="radarRows"
        :runs="runs"
        :busy-target="busyTarget"
        :msg="actionMsg"
        :loading="loading"
        :load-error="loadError"
        @claim="claimApp"
        @health="healthApp"
        @claim-many="claimMany"
        @claim-all="claimAllApps"
      />
      <TrafficPage
        v-else-if="active === '流量'"
        :rows="radarRows"
        :loading="loading"
        :collecting="collecting"
        :msg="usageMsg"
        :loaded-at="usageLoadedAt"
        @refresh="loadAll"
        @collect="collectUsage"
      />
      <LogPage v-else-if="active === '日志'" :runs="runs" />
      <SettingsPage
        v-else-if="active === '设置'"
        :settings="settings"
        :server-info="serverInfo"
        :gateway-routes="gatewayRoutes"
        :takes-effect="takesEffect"
        :routes-loading="loadingRoutes"
        :routes-busy="savingRoutes"
        :routes-msg="routesMsg"
        @update="updateSettings"
        @save-routes="saveRoutes"
        @reload-routes="loadRoutes"
      />
      <!-- 仪表盘：默认页 + 兜底（resolveActive 无 hash 也落这里） -->
      <DashboardPage
        v-else
        :accounts="accounts"
        :apps="apps"
        :runs="runs"
        :pending="pending"
        :radar-rows="radarRows"
        :today-done="todayDone"
        :claimable="claimable"
        :busy-target="busyTarget"
        :msg="actionMsg"
        :loading="loading"
        :load-error="loadError"
        :loaded-at="loadedAt"
        @claim="claimApp"
        @health="healthApp"
        @navigate="navigate"
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
