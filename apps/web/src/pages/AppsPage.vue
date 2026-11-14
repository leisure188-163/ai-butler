<script setup lang="ts">
/**
 * 应用页（ADR-013 六页 IA）：本机接入的各家 AI 助手名册。
 * 六列表 + 虚线邀请行 + 行展开；数据全部来自契约既有 AppOut/AccountOut，
 * 零新端点、零语义加工（能力标签只做协议 kind 的直译，signal 只消费分类）。
 */
import { computed, ref } from "vue";
import AppBadge from "../components/AppBadge.vue";
import type { AccountItem, AppItem, PageName, Signal } from "../types";
import { faceOf, signalText } from "../utils";

const props = defineProps<{
  apps: AppItem[];
  accounts: AccountItem[];
  busyTarget: string | null;
  msg: { text: string; tone: "ok" | "warn" } | null;
  loading: boolean;
  loadError: string;
}>();

const emit = defineEmits<{
  import: [target: string];
  importAll: [];
  jump: [page: PageName];
}>();

const emptyApps = computed(() => props.apps.filter((a) => !a.account_id));
const importableCount = computed(() => emptyApps.value.length);

function capabilityText(kind: string): string {
  if (kind === "provision.run") return "领取";
  if (kind === "health.check") return "体检";
  if (kind.startsWith("usage")) return "用量";
  return kind;
}

function accountCount(app: AppItem): number {
  if (app.account_ids?.length) return app.account_ids.length;
  return app.account_id ? 1 : 0;
}

function accountsOf(app: AppItem): AccountItem[] {
  const ids = new Set(app.account_ids ?? (app.account_id ? [app.account_id] : []));
  return props.accounts.filter((a) => ids.has(a.account_id) || a.provider === app.id);
}

const signals: Signal[] = ["ok", "notice", "attention", "danger", "quiet"];

function statusGroups(app: AppItem) {
  const list = accountsOf(app);
  return signals
    .map((signal) => ({ signal, count: list.filter((a) => a.signal === signal).length }))
    .filter((g) => g.count > 0);
}

const expandedId = ref<string | null>(null);

function toggleDetail(id: string) {
  expandedId.value = expandedId.value === id ? null : id;
}
</script>

<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">应用</h1>
        <p class="page-sub">本机接入的各家 AI 助手与其能力、时间表。</p>
      </div>
      <button
        class="btn btn--primary"
        :disabled="busyTarget !== null || !importableCount"
        @click="emit('importAll')"
      >一键导入{{ importableCount ? `（${importableCount}）` : "" }}</button>
    </div>
  </header>

  <p
    v-if="msg"
    class="action-msg"
    :class="msg.tone === 'ok' ? 'action-msg--ok' : 'action-msg--warn'"
    role="status"
  >{{ msg.text }}</p>

  <section class="section" aria-label="应用名册">
    <div v-if="apps.length" class="app-wrap sheet">
      <table class="matrix">
        <thead>
          <tr>
            <th>应用</th>
            <th>能力</th>
            <th>时间表</th>
            <th>账户数</th>
            <th>状态汇总</th>
            <th>动作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="app in apps" :key="app.id">
            <tr :class="{ 'is-selected': expandedId === app.id }" @click="toggleDetail(app.id)">
              <td>
                <AppBadge :name="app.display" :color-index="faceOf(app.id)" />
              </td>
              <td>
                <span v-for="cap in app.capabilities" :key="cap" class="tag tag--quiet cap-tag">
                  {{ capabilityText(cap) }}
                </span>
                <span v-if="!app.capabilities.length" class="faint">—</span>
              </td>
              <td class="num">{{ app.schedule_times.length ? app.schedule_times.join("、") : "—" }}</td>
              <td class="num">
                <span v-if="accountCount(app)">{{ accountCount(app) }}</span>
                <span v-else class="unimported">未导入</span>
              </td>
              <td>
                <span
                  v-for="g in statusGroups(app)"
                  :key="g.signal"
                  class="tag"
                  :class="`tag--${g.signal}`"
                >{{ signalText(g.signal) }} {{ g.count }}</span>
                <span v-if="!statusGroups(app).length" class="faint">—</span>
              </td>
              <td @click.stop>
                <span class="row-actions">
                  <button
                    v-if="!app.account_id"
                    class="btn btn--ghost"
                    :disabled="busyTarget !== null"
                    @click="emit('import', app.id)"
                  >导入</button>
                  <button v-else class="btn btn--ghost" @click="emit('jump', '账户')">去账户</button>
                  <button class="btn btn--ghost" @click="toggleDetail(app.id)">
                    {{ expandedId === app.id ? "收起" : "详情" }}
                  </button>
                </span>
              </td>
            </tr>
            <tr v-if="expandedId === app.id" class="detail-row">
              <td colspan="6" @click.stop>
                <ul class="rows">
                  <li class="row">
                    <span class="row-main">
                      <p class="row-title">能力清单</p>
                      <p class="row-sub mono">{{ app.capabilities.join(" · ") || "—" }}</p>
                    </span>
                  </li>
                  <li class="row">
                    <span class="row-main">
                      <p class="row-title">时间表</p>
                      <p class="row-sub">{{ app.schedule_times.join("、") || "—" }}</p>
                    </span>
                  </li>
                  <li class="row">
                    <span class="row-main">
                      <p class="row-title">该应用账户（{{ accountCount(app) }}）</p>
                      <p class="row-sub mono">
                        {{ accountsOf(app).map((a) => a.account_id).join("、") || "—" }}
                      </p>
                    </span>
                    <button class="btn btn--ghost" @click="emit('jump', '账户')">去账户</button>
                  </li>
                </ul>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- 未接入应用的虚位邀请行（从账户页迁入，ADR-013 §3） -->
    <ul v-if="emptyApps.length" class="slots" aria-label="可导入应用">
      <li v-for="app in emptyApps" :key="app.id">
        <button class="slot-row" :disabled="busyTarget !== null" @click="emit('import', app.id)">
          <span class="slot-plus" aria-hidden="true">＋</span>
          导入 {{ app.display }}
        </button>
      </li>
    </ul>

    <p v-if="!apps.length" class="quietline">
      还没有应用——一键导入把本机客户端接进来。
    </p>
  </section>
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
.app-wrap { overflow-x: auto; }
.app-wrap .matrix { min-width: 720px; }
.cap-tag { margin-right: var(--space-1); }
.faint { color: var(--color-text-faint); }
.unimported {
  color: var(--color-text-muted);
  border-bottom: 1px dashed var(--color-border);
}
.detail-row td {
  background: var(--color-surface-2);
  padding: var(--space-3) var(--space-4);
}
.slots {
  list-style: none;
  margin: var(--space-3) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.slot-row {
  box-sizing: border-box;
  width: 100%;
  border: 1.5px dashed var(--color-border);
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-size: var(--text-sm);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  cursor: pointer;
  transition:
    border-color var(--motion-base),
    color var(--motion-base);
}
.slot-row:hover:not(:disabled) { border-color: var(--color-accent); color: var(--color-accent); }
.slot-row:disabled { opacity: 0.45; cursor: not-allowed; }
.slot-plus { font-size: var(--text-lg); line-height: 1; }
</style>
