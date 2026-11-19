<script setup lang="ts">
/**
 * 平台页（ADR-010 六页 IA）：本机接入的各家 AI 助手名册。
 * 7 列 + 虚线邀请行；点击平台名弹详情，行内「修改」直接开编辑弹层。
 * 数据全部来自契约既有 Out 模型，零新端点、零语义加工。
 */
import { computed, ref, watch } from "vue";
import PlatformBadge from "../components/PlatformBadge.vue";
import PlatformDetail from "../components/PlatformDetail.vue";
import PlatformEditor from "../components/PlatformEditor.vue";
import PlatformFilters from "../components/PlatformFilters.vue";
import RowActionMenu from "../components/RowActionMenu.vue";
import type {
  AccountItem,
  CustomPlatformDraft,
  PageName,
  PlatformItem,
  PlatformPatch,
  PlatformQuery,
  RowAction,
  Signal,
} from "../types";
import { faceOf, signalText } from "../utils";
import { accessHint, accountCount, capabilityText, kindText, visibleCaps } from "../utils/platform";
import { platformIcon } from "../utils/platformIcons";
const props = defineProps<{
  platforms: PlatformItem[];
  accounts: AccountItem[];
  customCodes: string[];
  busyTarget: string | null;
  loading: boolean;
  loadError: string;
}>();
const emit = defineEmits<{
  claim: [target: string];
  import: [target: string];
  importAll: [];
  resync: [];
  savePlatform: [target: string, patch: PlatformPatch];
  saveCustom: [draft: CustomPlatformDraft];
  removeCustom: [code: string];
  jump: [page: PageName, platformCode?: string];
}>();
/** 弹层状态：详情 / 创建 / 修改，三者互斥；不往表格里塞详情行 */
const detailTarget = ref<PlatformItem | null>(null);
const editorMode = ref<"create" | "edit" | null>(null);
const editorTarget = ref<PlatformItem | null>(null);
const detailPlatform = computed(() =>
  detailTarget.value
    ? props.platforms.find((p) => p.id === detailTarget.value!.id) ?? detailTarget.value
    : null,
);
const editorPlatform = computed(() =>
  editorTarget.value
    ? props.platforms.find((p) => p.id === editorTarget.value!.id) ?? editorTarget.value
    : null,
);
function openDetail(platform: PlatformItem): void {
  detailTarget.value = platform;
}
function closeDetail(): void {
  detailTarget.value = null;
}
function openCreate(): void {
  detailTarget.value = null;
  editorTarget.value = null;
  editorMode.value = "create";
}
function openEdit(platform: PlatformItem): void {
  detailTarget.value = null;
  editorTarget.value = platform;
  editorMode.value = "edit";
}
function closeEditor(): void {
  editorMode.value = null;
  editorTarget.value = null;
}
function onSaveCustom(draft: CustomPlatformDraft): void {
  emit("saveCustom", draft);
  closeEditor();
}
function onSavePlatform(target: string, patch: PlatformPatch): void {
  emit("savePlatform", target, patch);
  closeEditor();
}
function isCustom(id: string): boolean {
  return props.customCodes.includes(id);
}
/** 行操作全部图标化（docs/conventions/07）：动作名只在 hover/读屏里出现 */
function primaryActions(platform: PlatformItem): RowAction[] {
  const out: RowAction[] = [{ key: "edit", label: "修改", icon: "edit", title: "修改平台信息" }];
  out.push({
    key: "import",
    label: accountCount(platform) ? "重新接入" : "接入",
    // 图标动作（2026-11-19）：文字只做 hover 说明与读屏名，按钮本身是循环箭头
    icon: "refresh",
    // 已接入平台的「重新接入」= 重连本机客户端并重读凭据，不是再登记一遍账户
    title: accountCount(platform)
      ? "重新连接本机客户端并重读凭据（换号、重装、重新登录客户端之后用）"
      : "连接本机客户端，读取凭据并登记账户",
  });
  return out;
}
function moreActions(platform: PlatformItem): RowAction[] {
  const out: RowAction[] = [];
  if (platform.capabilities.includes("provision.run")) out.push({ key: "claim", label: "立即领取" });
  if (isCustom(platform.id)) out.push({ key: "remove", label: "删除", danger: true });
  return out;
}
function runRowAction(platform: PlatformItem, key: string): void {
  if (key === "edit") openEdit(platform);
  else if (key === "import") emit("import", platform.id);
  else if (key === "claim") emit("claim", platform.id);
  else if (key === "remove") confirmRemove(platform.id);
}
function confirmRemove(id: string): void {
  if (!window.confirm(`删除自定义平台 ${id}？历史台账保留，但不再排班。`)) return;
  emit("removeCustom", id);
}
/** 启停一键切换（列表状态列） */
function toggleActive(platform: PlatformItem): void {
  emit("savePlatform", platform.id, { active: !platform.active });
}
/* 接入状态是唯一事实来源：有账户的平台进主表格，没账户的只进底部清单，两处互斥。 */
function isConnected(platform: PlatformItem): boolean {
  return accountCount(platform) > 0;
}
const connectedPlatforms = computed(() => props.platforms.filter(isConnected));
const emptyPlatforms = computed(() => props.platforms.filter((p) => !isConnected(p)));
const importableCount = computed(() => emptyPlatforms.value.length);
function accountsOf(platform: PlatformItem): AccountItem[] {
  const ids = new Set(platform.account_ids ?? (platform.account_id ? [platform.account_id] : []));
  return props.accounts.filter((a) => ids.has(a.account_id) || a.platform_code === platform.id);
}
const signals: Signal[] = ["ok", "notice", "attention", "danger", "quiet"];
function statusGroups(platform: PlatformItem) {
  const list = accountsOf(platform);
  return signals
    .map((signal) => ({ signal, count: list.filter((a) => a.signal === signal).length }))
    .filter((g) => g.count > 0);
}
/* 检索：关键字 + 状态 + 类型 + 排序，纯前端过滤，零新端点 */
const query = ref<PlatformQuery>({ keyword: "", status: "all", kind: "all", sort: "code" });
const filteredPlatforms = computed(() => {
  const keyword = query.value.keyword.trim().toLowerCase();
  const list = connectedPlatforms.value.filter((platform) => {
    if (query.value.status !== "all" && platform.active !== (query.value.status === "active")) {
      return false;
    }
    if (query.value.kind !== "all" && platform.kind !== query.value.kind) return false;
    if (!keyword) return true;
    return (
      platform.id.toLowerCase().includes(keyword) || platform.platform_name.toLowerCase().includes(keyword)
    );
  });
  const sorted = [...list];
  if (query.value.sort === "name") {
    sorted.sort((a, b) => a.platform_name.localeCompare(b.platform_name, "zh"));
  } else if (query.value.sort === "accounts") {
    sorted.sort((a, b) => accountCount(b) - accountCount(a) || a.id.localeCompare(b.id));
  } else {
    sorted.sort((a, b) => a.id.localeCompare(b.id));
  }
  return sorted;
});
/* 分页：每页 10 条 */
const PAGE_SIZE = 10;
const page = ref(1);
const totalPages = computed(() =>
  Math.max(1, Math.ceil(filteredPlatforms.value.length / PAGE_SIZE)),
);
const pagedPlatforms = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE;
  return filteredPlatforms.value.slice(start, start + PAGE_SIZE);
});
watch(query, () => { page.value = 1; }, { deep: true });
watch(
  () => connectedPlatforms.value.length,
  () => {
    if (page.value > totalPages.value) page.value = totalPages.value;
  },
);
function goPage(next: number) {
  page.value = Math.min(Math.max(1, next), totalPages.value);
}
/** 未接入平台清单默认收起 */
const slotsOpen = ref(false);
</script>
<template>
  <header class="head">
    <div class="head-row">
      <div>
        <h1 class="page-title">平台管理</h1>
        <p class="page-sub">
          平台来自内置连接器——本机装好并登录对应客户端后即可接入。
        </p>
      </div>
      <div class="head-actions">
        <button
          class="btn btn--primary"
          :disabled="busyTarget !== null"
          title="重新扫描连接器，把平台定义（类型/能力/版本/排班）写回名册——不导入账户；平台表被清空或连接器升级后用"
          @click="emit('resync')"
        >同步平台</button>
        <button class="btn" :disabled="busyTarget !== null" @click="openCreate">
          ＋ 自定义平台
        </button>
        <!-- 批量接入只在「有未接入平台」时出现：无空位时留一个永远点不动的按钮是噪音 -->
        <button
          v-if="importableCount"
          class="btn"
          :disabled="busyTarget !== null"
          title="对所有尚未接入的平台逐个执行接入（等同逐行点「接入」）"
          @click="emit('importAll')"
        >接入全部（{{ importableCount }}）</button>
      </div>
    </div>
  </header>
  <PlatformDetail
    v-if="detailPlatform"
    :platform="detailPlatform"
    :accounts="accountsOf(detailPlatform)"
    :busy="busyTarget !== null"
    @close="closeDetail"
    @edit="openEdit(detailPlatform)"
  />
  <PlatformEditor
    v-if="editorMode !== null"
    :mode="editorMode"
    :platform="editorPlatform"
    :saving="busyTarget !== null"
    @close="closeEditor"
    @save-custom="onSaveCustom"
    @save-platform="onSavePlatform"
  />
  <section class="section" aria-label="平台名册">
    <PlatformFilters
      v-model:keyword="query.keyword"
      v-model:status="query.status"
      v-model:kind="query.kind"
      v-model:sort="query.sort"
    />
    <div class="platform-wrap sheet">
      <table class="matrix">
        <thead>
          <tr>
            <th class="col-identity">平台名称</th>
            <th class="col-code">平台编码</th>
            <th class="col-kind">类型</th>
            <th class="col-version">版本</th>
            <th class="col-state">状态</th>
            <th class="col-caps">能力</th>
            <th class="col-sched">调度执行时间</th>
            <th class="col-anchor">账户</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!pagedPlatforms.length">
            <td class="table-empty" colspan="9">暂无平台数据</td>
          </tr>
          <tr v-for="platform in pagedPlatforms" :key="platform.id">
            <!-- 身份锚点：名称与编码各占一列；点名称弹详情，不再展开表格行。
                 可点提示用「轻」的表达（2026-11-19 用户否掉了「详情」文字胶囊）：
                 名称末尾一枚极小的 › 箭头常驻，hover 时名称转主色并出现下划线。 -->
            <td class="identity-cell">
              <button class="platform-open" :aria-label="`查看 ${platform.platform_name} 详情`" @click="openDetail(platform)">
                <span class="identity-name">
                  <PlatformBadge :name="platform.platform_name" :color-index="faceOf(platform.id)" :icon="platformIcon(platform.id)" />
                  <span v-if="isCustom(platform.id)" class="tag tag--notice">自定义</span>
                  <span class="open-arrow" aria-hidden="true">›</span>
                </span>
              </button>
            </td>
            <td class="col-code">
              <span class="mono identity-code">{{ platform.id }}</span>
            </td>
            <td class="col-kind">
              <span class="tag tag--quiet">{{ platform.kind ? kindText(platform.kind) : "—" }}</span>
            </td>
            <!-- 版本单列：网页版无客户端版本，写「—」；客户端探不到时如实说「版本未知」，不留空 -->
            <td class="col-version">
              <span v-if="platform.client_version" class="ver num">v{{ platform.client_version }}</span>
              <span v-else-if="platform.kind === 'client'" class="ver faint">版本未知</span>
              <span v-else class="faint">—</span>
            </td>
            <td class="col-state">
              <button
                class="state-switch"
                :class="platform.active ? 'is-on' : 'is-off'"
                :disabled="busyTarget !== null"
                :aria-pressed="platform.active"
                :aria-label="`${platform.platform_name}：${platform.active ? '已启用，点击停用' : '已停用，点击启用'}`"
                :title="platform.active ? '点击停用' : '点击启用'"
                @click="toggleActive(platform)"
              >
                <span class="switch-track"><span class="switch-thumb"></span></span>
                <span class="switch-label">{{ platform.active ? "启用" : "已停用" }}</span>
              </button>
            </td>
            <td class="col-caps">
              <span v-for="cap in visibleCaps(platform)" :key="cap" class="tag tag--quiet cap-tag">
                {{ capabilityText(cap) }}
              </span>
              <span v-if="!visibleCaps(platform).length" class="faint">—</span>
            </td>
            <td class="col-sched">
              <div class="num sched-times">{{ platform.schedule_times.join(" · ") || "—" }}</div>
              <div class="sched-count">
                {{ platform.schedule_times.length ? `每日 ${platform.schedule_times.length} 次` : "未排班" }}
                <span v-if="platform.schedule_overridden" class="tag tag--quiet">自定义</span>
              </div>
            </td>
            <td class="col-anchor">
              <div class="anchor-line">
                <span v-if="accountCount(platform)" class="anchor-count num">{{ accountCount(platform) }}</span>
                <span v-else class="unimported">未接入</span>
                <span v-if="accountCount(platform)" class="health-dots">
                  <span
                    v-for="(g, i) in statusGroups(platform)"
                    :key="g.signal"
                    class="health-dot"
                    :class="`health-dot--${g.signal}`"
                    :title="`${signalText(g.signal)} ${g.count}`"
                    :data-i="i"
                  ></span>
                </span>
              </div>
              <button
                v-if="accountCount(platform)"
                class="link-btn"
                @click.stop="emit('jump', '账户管理', platform.id)"
              >查看账户 ›</button>
            </td>
            <td class="col-actions" @click.stop>
              <RowActionMenu
                :inline="primaryActions(platform)"
                :more="moreActions(platform)"
                :busy="busyTarget !== null"
                @run="(key) => runRowAction(platform, key)"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <nav v-if="connectedPlatforms.length" class="pager" aria-label="平台分页">
      <button class="btn btn--ghost" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span class="pager-info">
        第 {{ page }} / {{ totalPages }} 页 · 共 {{ filteredPlatforms.length }} 个平台
      </span>
      <button class="btn btn--ghost" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
    </nav>
    <div v-if="emptyPlatforms.length" class="slots-fold">
      <button class="fold-head fold-head--page" :aria-expanded="slotsOpen" @click="slotsOpen = !slotsOpen">
        <span class="fold-caret">{{ slotsOpen ? "▾" : "▸" }}</span>
        尚未接入的平台（{{ emptyPlatforms.length }}）
        <span class="fold-hint">{{ slotsOpen ? "收起" : "展开可逐家接入" }}</span>
      </button>
      <ul v-if="slotsOpen" class="slots" aria-label="可接入平台">
        <li v-for="platform in emptyPlatforms" :key="platform.id">
          <button class="slot-row" :disabled="busyTarget !== null" @click="emit('import', platform.id)">
            <span class="slot-plus" aria-hidden="true">＋</span>
            <span class="slot-body">
              <span class="slot-name">接入 {{ platform.platform_name }}（{{ platform.id }}）</span>
              <span class="slot-hint">{{ accessHint(platform) }}</span>
            </span>
          </button>
        </li>
      </ul>
    </div>
    <p v-if="connectedPlatforms.length && !filteredPlatforms.length" class="quietline">
      没有匹配的平台——换个关键字，或点「清除筛选」。
    </p>
  </section>
</template>
<style scoped>
.platform-wrap .matrix { min-width: 1040px; }
.identity-cell { min-width: 140px; }
/* 编码独立成列（2026-11-19 用户裁决）：等宽小字、不换行，宽度不够时省略 */
.col-code { white-space: nowrap; }
.col-code .identity-code { display: block; max-width: 150px; overflow: hidden; text-overflow: ellipsis; }
.col-state { width: 96px; min-width: 96px; max-width: 96px; }
.platform-open {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.platform-open:hover .identity-name { color: var(--color-accent); }
.platform-open:hover .identity-name .badge-name {
  text-decoration: underline;
  text-decoration-color: var(--color-accent);
  text-underline-offset: 3px;
}
.platform-open:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 3px; }
.identity-name { display: flex; align-items: center; gap: var(--space-1); font-weight: 600; }
/* › 只做「可进入」的暗示：faint 灰、跟名称同字号，不占额外宽度 */
.open-arrow {
  flex: none;
  color: var(--color-text-muted);
  font-weight: 400;
  font-size: var(--text-xs);
  line-height: 1;
}
.platform-open:hover .open-arrow { color: var(--color-accent); }
.identity-code { font-size: var(--text-xs); color: var(--color-text-muted); }
/* 类型与版本各占一列（2026-11-19 用户要求拆开）：两列都窄、都 nowrap，拼起来与原「类型·版本」同宽 */
.col-kind { white-space: nowrap; width: 76px; }
.col-version { white-space: nowrap; width: 96px; }
.col-version .ver { font-size: var(--text-xs); color: var(--color-text-muted); }
/* 列表规范 07：表头与短列内容居中；.row-actions 是 flex，得单独居中 */
.platform-wrap .matrix th { text-align: center; }
.platform-wrap .matrix td.col-kind, td.col-version, td.col-state, td.col-anchor, td.col-actions { text-align: center; }
.platform-wrap .matrix .row-actions { justify-content: center; }
.state-switch {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 2px 0;
  border: 0;
  background: none;
  color: var(--color-text);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
  white-space: nowrap;
}
.state-switch:disabled { opacity: 0.45; cursor: not-allowed; }
.switch-track {
  position: relative;
  flex: none;
  width: 30px;
  height: 17px;
  border-radius: 999px;
  background: var(--color-quiet);
  transition: background var(--motion-base);
}
.switch-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
  transition: transform var(--motion-base);
}
.state-switch.is-on .switch-track { background: var(--color-accent); }
.state-switch.is-on .switch-thumb { transform: translateX(13px); }
.switch-label { font-variant-numeric: tabular-nums; }
.state-switch:hover:not(:disabled) .switch-label { color: var(--color-accent); }
.state-switch:focus-visible { border-radius: var(--radius-sm); }
.health-dots { display: inline-flex; gap: 3px; margin-left: var(--space-2); }
.health-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.health-dot--ok { background: var(--color-ok); }
.health-dot--notice { background: var(--color-notice); }
.health-dot--attention { background: var(--color-attention); }
.health-dot--danger { background: var(--color-danger); }
.health-dot--quiet { background: var(--color-quiet); }
.anchor-line { display: flex; align-items: center; justify-content: center; }
/* 账户列与操作列定宽（2026-11-19）：窄窗口自适应后这两列被压出折行，定宽后胶囊单行、图标并排 */
.col-anchor { width: 112px; }
.col-actions { width: 156px; }
.anchor-count { font-weight: 600; }
/* 「查看账户」是下钻入口，不是装饰文字：做成描边胶囊（2026-11-19 用户要求
   「一看就知道可以点开详情」）。纯文字 + hover 下划线的弱链接在表格里没人认得。 */
.link-btn {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  white-space: nowrap;
  margin-top: var(--space-1);
  padding: 1px var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-chip);
  background: var(--color-surface-2);
  color: var(--color-accent);
  font: inherit;
  font-size: var(--text-xs);
  line-height: 1.7;
  cursor: pointer;
}
.link-btn:hover {
  border-color: var(--color-accent);
  background: var(--color-accent-weak);
}
.link-btn:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 1px;
}
.sched-times { font-size: var(--text-sm); }
.sched-count { font-size: var(--text-xs); color: var(--color-text-faint); }
.sched-count .tag { margin-left: var(--space-1); }
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
  gap: var(--space-2);
  flex-wrap: wrap;
}
.platform-wrap { overflow-x: auto; }
@media (max-width: 1100px) {
  .col-caps { display: none; }
  /* 能力列收掉后不再撑 1040px 底宽：让表格按内容自适应，窗口够宽就全显示 */
  .platform-wrap .matrix { min-width: 0; }
}
@media (max-width: 900px) {
  .col-sched { display: none; }
}
@media (max-width: 720px) {
  .col-kind, .col-version { display: none; }
}
@media (max-width: 640px) {
  .platform-wrap { overflow-x: visible; }
  .platform-wrap .matrix { min-width: 0; }
  .row-actions { display: grid; grid-template-columns: repeat(2, auto); justify-content: start; gap: 2px var(--space-2); }
  .row-actions .btn { padding: 2px var(--space-2); }
}
.fold-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) 0;
  background: none;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text);
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
}
.fold-head:hover { color: var(--color-accent); }
.fold-caret { width: 1em; color: var(--color-text-muted); }
.fold-hint { margin-left: auto; color: var(--color-text-muted); font-size: var(--text-xs); }
.quietline--warn { color: var(--color-attention); }
.slots-fold { margin-top: var(--space-4); }
.fold-head--page { border-top: 1px solid var(--color-border); }
.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-3);
}
.pager-info { font-size: var(--text-xs); color: var(--color-text-muted); }
.cap-tag { margin-right: var(--space-1); }
.faint { color: var(--color-text-faint); }
.unimported {
  color: var(--color-text-muted);
  border-bottom: 1px dashed var(--color-border);
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
.slot-body { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; }
.slot-name { color: inherit; font-size: var(--text-sm); }
.slot-hint { color: var(--color-text-faint); font-size: var(--text-xs); }
</style>
