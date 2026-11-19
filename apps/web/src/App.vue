<script setup lang="ts">
/**
 * Butler 管理台 · 平台壳（ADR-010 六页 IA，仪表盘默认）
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import SideNav from "./components/SideNav.vue";
import DashboardPage from "./pages/DashboardPage.vue";
import PlatformsPage from "./pages/PlatformsPage.vue";
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
import { useToast } from "./composables/useToast";
import AppToast from "./components/AppToast.vue";

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
  platforms,
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
  customPlatforms,
  loadCustomPlatforms,
  createCustomPlatform,
  removeCustomPlatform,
  importPlatform,
  savePlatform,
  claimApp,
  healthApp,
  repairAccount,
  importAllPlatforms,
  resyncPlatforms,
  claimAllApps,
  claimMany,
  scanSessions,
  renameAccount,
} = account;
const { collecting, usageMsg, collectUsage } = usage;

/* 自定义平台目录（2026-11-18）：名册里的「自定义」徽章与删除入口用它判定；
   新建/删除动作内部会重拉目录，这里只在首屏补一次 */
onMounted(() => {
  void loadCustomPlatforms().catch(() => undefined);
});

/* 平台页「查看账户」下钻：记住目标平台，账户页据此预置分组筛选（重设计 v1） */
const accountFocus = ref<string | null>(null);
function jumpToPage(page: import("./types").PageName, platformCode?: string) {
  accountFocus.value = platformCode ?? null;
  if (platformCode) active.value = "账户管理";
  navigate(page);
}
/* 离开账户页后清掉下钻筛选——下次从侧栏进账户页应看全量，不带上一次的目标平台 */
watch(active, (page) => {
  if (page !== "账户管理") accountFocus.value = null;
});

/* ---- 统一提示（2026-11-19 用户裁决）----
   各域仍写各自的 msg 状态（语义不动），这里统一桥接到居中 Toast（3 秒自动消失）。
   逐源独立 watch：只有该源**自己**变化才弹——若把三源合成一个 watch，某源持有旧值时
   另一源一变就会用旧文案重新 show，倒计时被无限重置（实测过，永不消失）。 */
const toast = useToast();
function pushToast(msg: { text: string; tone: "ok" | "warn" } | null) {
  if (msg) toast.show(msg.text, msg.tone === "warn" ? "warn" : "ok");
}
watch(actionMsg, pushToast);
watch(usageMsg, pushToast);
watch(routesMsg, pushToast);

/* 待办栏可领取 target 集合（纯派生：申报了 provision.run 且已导入的平台） */
const claimable = computed(
  () =>
    new Set(
      platforms.value
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
  if (active.value === "系统设置") loadRoutes();
});

/* 进设置页时装载路由表（设置页局部数据不进轮询，R4-G6） */
watch(active, (page) => {
  if (page === "系统设置") loadRoutes();
});

onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer);
});
</script>

<template>
  <div class="shell">
    <AppToast />
    <SideNav
      :active="active"
      :alert-count="alertCount"
      :loading="loading"
      :loaded-at="loadedAt"
      :theme="settings.theme"
      @navigate="navigate"
      @refresh="loadAll"
    />

    <main class="content" :class="{ 'content--qinglan': settings.theme === 'qinglan' }">
      <p v-if="loadError" class="errorline" role="alert">{{ loadError }}</p>

      <PlatformsPage
        v-if="active === '平台管理'"
        :platforms="platforms"
        :accounts="accounts"
        :custom-codes="customPlatforms.map((p) => p.code)"
        :busy-target="busyTarget"
        :loading="loading"
        :load-error="loadError"
        @claim="claimApp"
        @import="importPlatform"
        @import-all="importAllPlatforms"
        @resync="resyncPlatforms"
        @save-platform="savePlatform"
        @save-custom="createCustomPlatform"
        @remove-custom="removeCustomPlatform"
        @jump="jumpToPage"
      />
      <AccountsPage
        v-else-if="active === '账户管理'"
        :accounts="accounts"
        :platforms="platforms"
        :radar="radarRows"
        :runs="runs"
        :busy-target="busyTarget"
        :initial-platform="accountFocus"
        :loading="loading"
        :load-error="loadError"
        @claim="claimApp"
        @health="healthApp"
        @claim-many="claimMany"
        @claim-all="claimAllApps"
        @scan-sessions="scanSessions"
        @repair="repairAccount"
        @rename="renameAccount"
      />
      <TrafficPage
        v-else-if="active === '用量管理'"
        :rows="radarRows"
        :loading="loading"
        :collecting="collecting"
        :loaded-at="usageLoadedAt"
        @collect="collectUsage"
      />
      <LogPage v-else-if="active === '运行日志'" :runs="runs" />
      <SettingsPage
        v-else-if="active === '系统设置'"
        :settings="settings"
        :server-info="serverInfo"
        :gateway-routes="gatewayRoutes"
        :takes-effect="takesEffect"
        :routes-loading="loadingRoutes"
        :routes-busy="savingRoutes"
        @update="updateSettings"
        @save-routes="saveRoutes"
        @reload-routes="loadRoutes"
      />
      <!-- 仪表盘：默认页 + 兜底（resolveActive 无 hash 也落这里） -->
      <DashboardPage
        v-else
        :accounts="accounts"
        :platforms="platforms"
        :runs="runs"
        :pending="pending"
        :radar-rows="radarRows"
        :today-done="todayDone"
        :claimable="claimable"
        :busy-target="busyTarget"
        :loading="loading"
        :load-error="loadError"
        :loaded-at="loadedAt"
        @claim="claimApp"
        @health="healthApp"
        @navigate="navigate"
        @repair="repairAccount"
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
  /* 2026-11-18 改版：原来 max-width 1160 + margin:0 auto 会在宽屏把内容浮到
     屏幕正中，侧栏与内容之间空出 200~300px（"两栏隔得老远"）。现改为左贴侧栏、
     右侧自然留白，并把上限抬到 1440——表格页多一列也不至于刚过 1160 就横滚。 */
  max-width: 1440px;
  margin-right: auto;
  padding: var(--space-6) var(--space-6) var(--space-8);
  box-sizing: border-box;
}
/* 青岚山水：内容区顶部淡远山底色（纯 CSS 层叠山峦，pointer-events:none 不挡交互） */
.content--qinglan { position: relative; }
.content--qinglan::before {
  content: "";
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 130px;
  pointer-events: none;
  z-index: 0;
  background:
    radial-gradient(ellipse 60% 100% at 18% 100%, rgba(157, 204, 181, 0.32) 0%, transparent 100%),
    radial-gradient(ellipse 55% 100% at 55% 100%, rgba(122, 184, 154, 0.26) 0%, transparent 100%),
    radial-gradient(ellipse 65% 100% at 88% 100%, rgba(157, 204, 181, 0.30) 0%, transparent 100%),
    linear-gradient(180deg, rgba(238, 246, 242, 0) 0%, rgba(238, 246, 242, 0.7) 100%);
}
.content--qinglan > * { position: relative; z-index: 1; }

/* 与 SideNav 的 900px 断点配套：侧栏变顶部横条，壳随之转纵向，否则 main 被挤出屏 */
@media (max-width: 900px) {
  .shell { flex-direction: column; }
  /* 纵排时侧栏变顶部横条，margin-right 不再起作用（宽度已 100%） */
  .content { width: 100%; margin-right: 0; }
}

@media (max-width: 640px) {
  .content { padding: var(--space-5) var(--space-4) var(--space-8); }
}
</style>
