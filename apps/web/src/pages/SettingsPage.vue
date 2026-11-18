<script setup lang="ts">
/**
 * 设置页：通用/提醒规则/关于 + 网关路由（R4-G6）。
 * 路由表编辑 = 本地草稿行（accounts 逗号分隔），保存时整表替换下发——
 * 校验单源在 core（UI 不复写规则），422 detail 直显不加工（红线 2/4）。
 */
import { ref, watch } from "vue";
import type { GatewayRouteRule, Settings, ThemeName } from "../types";
import { docsUrl } from "../utils";

const props = defineProps<{
  settings: Settings;
  serverInfo: { title: string; version: string } | null;
  gatewayRoutes: GatewayRouteRule[];
  takesEffect: string;
  routesLoading: boolean;
  routesBusy: boolean;
  routesMsg: { text: string; tone: "ok" | "warn" } | null;
}>();

const emit = defineEmits<{
  update: [patch: Partial<Settings>];
  saveRoutes: [rows: { model: string; accounts: string[] }[]];
  reloadRoutes: [];
}>();

/** 接口文档：同源派生（不写死端口——dev 走 vite 代理，生产/sidecar 同源伺服） */
const docsHref = docsUrl();
const docsLabel = docsHref.replace(/^https?:\/\//, "");

function onIntervalChange(event: Event) {
  emit("update", { intervalSec: Number((event.target as HTMLSelectElement).value) });
}

function onThemeChange(event: Event) {
  emit("update", { theme: (event.target as HTMLSelectElement).value as ThemeName });
}

/* ---- 网关路由草稿（accounts 编辑态 = 逗号分隔串；server 出规范表，草稿只服务输入） ---- */
interface RouteDraft {
  model: string;
  accounts: string;
}

const routeDrafts = ref<RouteDraft[]>([]);
const draftWarn = ref("");

watch(
  () => props.gatewayRoutes,
  (rules) => {
    routeDrafts.value = rules.map((r) => ({ model: r.model, accounts: r.accounts.join(", ") }));
    draftWarn.value = "";
  },
  { immediate: true },
);

function addRoute() {
  routeDrafts.value.push({ model: "", accounts: "" });
}

function removeRoute(index: number) {
  routeDrafts.value.splice(index, 1);
}

function resetRoutes() {
  emit("reloadRoutes");
  routeDrafts.value = props.gatewayRoutes.map((r) => ({
    model: r.model,
    accounts: r.accounts.join(", "),
  }));
}

function saveRoutes() {
  draftWarn.value = "";
  // 表单完整性预处理（UI 职责，非业务规则）：全空行剔除；半空行本地拦下不发——
  // 业务校验单源在 core/server，422 detail 直显（红线 2/4）
  const rows = routeDrafts.value.map((d) => ({
    model: d.model.trim(),
    accounts: d.accounts
      .split(/[，,]/)
      .map((a) => a.trim())
      .filter(Boolean),
  }));
  const meaningful = rows.filter((r) => r.model || r.accounts.length);
  const halfEmpty = meaningful.findIndex((r) => !r.model || !r.accounts.length);
  if (halfEmpty >= 0) {
    draftWarn.value = `第 ${halfEmpty + 1} 行不完整：模型名与账户池都要填（多账户用逗号分隔）。`;
    return;
  }
  emit("saveRoutes", meaningful);
}
</script>

<template>
  <header class="head">
    <h1 class="page-title">系统设置</h1>
    <p class="page-sub">改动即时生效，保存在本机浏览器。</p>
  </header>

  <section class="section" aria-label="通用">
    <h2 class="section-title">通用</h2>
    <div class="sheet">
      <div class="field">
        <label class="field-label" for="set-theme">主题</label>
        <select id="set-theme" class="input" :value="settings.theme" @change="onThemeChange">
          <option value="system">跟随系统</option>
          <option value="qinglan">青岚山水</option>
          <option value="paper">纸墨东方</option>
          <option value="dark">深空控制台</option>
          <option value="mist">精工浅色</option>
        </select>
      </div>
      <div class="field">
        <label class="field-label" for="set-autorefresh">自动刷新</label>
        <button
          id="set-autorefresh"
          class="switch"
          role="switch"
          :aria-checked="settings.autoRefresh"
          @click="emit('update', { autoRefresh: !settings.autoRefresh })"
        ></button>
      </div>
      <div class="field">
        <label class="field-label" for="set-interval">刷新间隔</label>
        <select
          id="set-interval"
          class="input"
          :disabled="!settings.autoRefresh"
          :value="settings.intervalSec"
          @change="onIntervalChange"
        >
          <option :value="30">30 秒</option>
          <option :value="60">60 秒</option>
          <option :value="120">2 分钟</option>
          <option :value="300">5 分钟</option>
        </select>
      </div>
    </div>
  </section>

  <section class="section" aria-label="提醒规则">
    <h2 class="section-title">提醒规则</h2>
    <div class="sheet">
      <div class="field">
        <span class="field-label">到期预警窗</span>
        <span class="field-value">3 天</span>
      </div>
      <div class="field">
        <span class="field-label">连续无授权判风险</span>
        <span class="field-value">3 次</span>
      </div>
    </div>
    <p class="quietline">规则值由 core 统一常量定义，暂不开放修改。</p>
  </section>

  <section class="section" aria-label="网关路由">
    <h2 class="section-title">网关路由</h2>
    <div class="sheet">
      <p v-if="routesLoading" class="quietline">路由表读取中…</p>
      <template v-else>
        <p v-if="!routeDrafts.length" class="quietline">
          没有路由规则——网关对所有模型返回「未配置路由」。添加规则把模型指到有序账户池。
        </p>
        <div
          v-for="(draft, index) in routeDrafts"
          :key="index"
          class="route-row"
          aria-label="路由规则行"
        >
          <input
            v-model="draft.model"
            class="input route-model"
            type="text"
            placeholder="模型名（如 gpt-x）"
            :aria-label="`第 ${index + 1} 条规则的模型名`"
          />
          <input
            v-model="draft.accounts"
            class="input route-accounts"
            type="text"
            placeholder="账户 id（逗号分隔，先 = 优先）"
            :aria-label="`第 ${index + 1} 条规则的候选账户`"
          />
          <button
            class="btn btn--ghost route-remove"
            type="button"
            @click="removeRoute(index)"
          >移除</button>
        </div>
        <div class="route-actions">
          <button class="btn btn--ghost" type="button" @click="addRoute">添加规则</button>
          <button class="btn btn--ghost" type="button" :disabled="routesBusy" @click="resetRoutes">
            重置
          </button>
          <button
            class="btn btn--primary"
            type="button"
            :disabled="routesBusy"
            @click="saveRoutes"
          >{{ routesBusy ? "保存中…" : "保存路由表" }}</button>
        </div>
        <p v-if="routesMsg" class="action-msg" :class="`action-msg--${routesMsg.tone}`" role="status">
          {{ routesMsg.text }}
        </p>
        <p v-else-if="draftWarn" class="action-msg action-msg--warn" role="status">{{ draftWarn }}</p>
        <p v-else-if="takesEffect" class="quietline">{{ takesEffect }}</p>
        <p v-else class="quietline">账户顺序即优先级；非法表会被拒绝（模型重复/字段为空）。</p>
      </template>
    </div>
  </section>

  <section class="section" aria-label="关于">
    <h2 class="section-title">关于</h2>
    <div class="sheet">
      <div class="field">
        <span class="field-label">产品</span>
        <span class="field-value">AI 智能助手管家（Butler）</span>
      </div>
      <div class="field">
        <span class="field-label">版本</span>
        <span class="field-value mono">
          {{ serverInfo ? `${serverInfo.title} ${serverInfo.version}` : "—" }}
        </span>
      </div>
      <div class="field">
        <span class="field-label">数据位置</span>
        <span class="field-value">butler.db（平台标准数据根）</span>
      </div>
      <div class="field">
        <span class="field-label">仓库</span>
        <a
          class="field-link"
          href="https://gitee.com/hiclaw_520/ai-butler"
          target="_blank"
          rel="noreferrer"
        >gitee.com/hiclaw_520/ai-butler</a>
      </div>
      <div class="field">
        <span class="field-label">接口文档</span>
        <a
          class="field-link"
          :href="docsHref"
          target="_blank"
          rel="noreferrer"
        >{{ docsLabel }}</a>
      </div>
    </div>
  </section>
</template>

<style scoped>
.head { padding-top: var(--space-2); }
.section .quietline { margin-top: var(--space-2); }

/* 路由规则行：模型窄列 + 账户宽列 + 移除；布局类自持，颜色字号一律 token */
.route-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  padding: var(--space-1) 0;
}
.route-model { flex: 0 0 180px; }
.route-accounts { flex: 1; min-width: 0; }
.route-remove { flex: none; }
.route-actions {
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
  margin-top: var(--space-3);
}
</style>
