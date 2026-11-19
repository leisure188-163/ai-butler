<script setup lang="ts">
/**
 * 平台编辑弹层（2026-11-19）：创建自定义平台与修改已有平台共用同一个 Vue 组件。
 *
 * create：把人话表单渲染成 CustomPlatformDraft，由调用方交给 createCustomPlatform。
 * edit：只提交契约开放的 platform_name / active / schedule_times 差量；编码、类型、版本、
 * 能力、凭据来自连接器探测，保持只读。
 * 调度执行时间两态共用 ScheduleTimesField，避免“创建一套 / 修改另一套”。
 */
import { computed, reactive, ref, watch } from "vue";
import ModalShell from "./ModalShell.vue";
import ScheduleTimesField from "./ScheduleTimesField.vue";
import type { CustomPlatformDraft, PlatformItem, PlatformPatch } from "../types";

const props = defineProps<{
  mode: "create" | "edit";
  platform?: PlatformItem | null;
  saving: boolean;
}>();

const emit = defineEmits<{
  close: [];
  saveCustom: [draft: CustomPlatformDraft];
  savePlatform: [target: string, patch: PlatformPatch];
}>();

const isEdit = computed(() => props.mode === "edit");

const create = reactive({
  code: "",
  display: "",
  domain: "",
  cookies: "",
  statusMethod: "GET",
  statusUrl: "",
  statusBody: "",
  judgeMode: "code" as "code" | "bool",
  codePath: "code",
  expectOk: "0",
  checkedInPath: "data.checked_in",
  claimMethod: "POST",
  claimUrl: "",
  claimBody: "",
  times: [] as string[],
});

const error = ref("");
const editName = ref("");
const editActive = ref(true);
const editTimes = ref<string[]>([]);

watch(
  () => props.platform,
  (platform) => {
    if (!isEdit.value || !platform) return;
    editName.value = platform.platform_name;
    editActive.value = platform.active;
    editTimes.value = [...platform.schedule_times];
  },
  { immediate: true },
);

const codeOk = computed(() => /^[a-z][a-z0-9_]{1,31}$/.test(create.code.trim()));

const canSave = computed(() => {
  if (!isEdit.value) {
    return (
      codeOk.value &&
      create.display.trim() !== "" &&
      create.domain.trim() !== "" &&
      create.cookies.trim() !== "" &&
      create.statusUrl.trim() !== "" &&
      create.claimUrl.trim() !== ""
    );
  }
  return !!props.platform;
});

const dialogTitle = computed(() =>
  isEdit.value ? `修改 · ${props.platform?.platform_name ?? ""}` : "创建自定义平台",
);

function parseBody(text: string): Record<string, unknown> {
  const raw = text.trim();
  if (!raw) return {};
  const parsed = JSON.parse(raw);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("请求体必须是 JSON 对象，例如 {\"req_source\": 1}");
  }
  return parsed as Record<string, unknown>;
}

function normalizeTimes(times: string[]): string[] {
  return [...new Set(times.map((time) => time.trim()).filter((time) => /^([01]\d|2[0-3]):[0-5]\d$/.test(time)))].sort();
}

function submitCreate(): void {
  const draft: CustomPlatformDraft = {
    code: create.code.trim(),
    display: create.display.trim(),
    domain: create.domain.trim(),
    cookies: create.cookies
      .split(/[,，\s]+/)
      .map((cookie) => cookie.trim())
      .filter(Boolean),
    status: {
      request: {
        method: create.statusMethod as "GET" | "POST",
        url: create.statusUrl.trim(),
        body: parseBody(create.statusBody),
      },
      checked_in_path: create.judgeMode === "bool" ? create.checkedInPath.trim() : "",
      code_path: create.codePath.trim() || "code",
      expect_ok: create.expectOk.trim() || "0",
    },
    claim: {
      request: {
        method: create.claimMethod as "GET" | "POST",
        url: create.claimUrl.trim(),
        body: parseBody(create.claimBody),
      },
      code_path: create.codePath.trim() || "code",
      expect_ok: create.expectOk.trim() || "0",
      retry_on_codes: [],
    },
    schedule_times: normalizeTimes(create.times),
  };
  emit("saveCustom", draft);
}

function submitEdit(): void {
  const platform = props.platform;
  if (!platform) return;
  const patch: PlatformPatch = {};
  const name = editName.value.trim();
  const times = normalizeTimes(editTimes.value);
  if (name !== platform.platform_name) patch.platform_name = name;
  if (editActive.value !== platform.active) patch.active = editActive.value;
  if (JSON.stringify(times) !== JSON.stringify(platform.schedule_times)) patch.times = times;
  if (Object.keys(patch).length) emit("savePlatform", platform.id, patch);
}

function submit(): void {
  error.value = "";
  try {
    if (isEdit.value) submitEdit();
    else submitCreate();
    emit("close");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

function resetName(): void {
  if (!props.platform) return;
  emit("savePlatform", props.platform.id, { platform_name: "" });
  emit("close");
}

function resetSchedule(): void {
  if (!props.platform) return;
  emit("savePlatform", props.platform.id, { times: null });
  emit("close");
}
</script>

<template>
  <ModalShell :title="dialogTitle" :busy="saving" @close="emit('close')">
    <template v-if="!isEdit">
      <section class="cpf-sec">
        <div class="cpf-sec-head">
          <h3 class="cpf-sec-title">基本信息</h3>
        </div>
        <div class="cpf-cols">
          <label class="cpf-field">
            <span class="cpf-label">平台编码</span>
            <input v-model="create.code" class="cpf-input mono" placeholder="mysite" />
            <span class="cpf-hint" :class="{ 'cpf-hint--bad': create.code && !codeOk }">
              小写字母开头，仅 a-z / 0-9 / _，2–32 位
            </span>
          </label>
          <label class="cpf-field">
            <span class="cpf-label">平台名称</span>
            <input v-model="create.display" class="cpf-input" placeholder="My Site" />
            <span class="cpf-hint">列表与台账里显示的名字</span>
          </label>
          <label class="cpf-field">
            <span class="cpf-label">登录域名</span>
            <input v-model="create.domain" class="cpf-input mono" placeholder="mysite.com" />
            <span class="cpf-hint">用于在本机 Chrome 的 cookie 库里匹配站点</span>
          </label>
          <label class="cpf-field">
            <span class="cpf-label">登录态 cookie 名</span>
            <input v-model="create.cookies" class="cpf-input mono" placeholder="sessionid, token" />
            <span class="cpf-hint">逗号分隔；这些 cookie 全在才算已登录</span>
          </label>
        </div>
      </section>

      <section class="cpf-sec">
        <div class="cpf-sec-head">
          <h3 class="cpf-sec-title">状态查询</h3>
        </div>
        <div class="cpf-stack">
          <div class="cpf-field">
            <span class="cpf-label">请求</span>
            <div class="cpf-row">
              <select v-model="create.statusMethod" class="cpf-input cpf-input--method">
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select>
              <input v-model="create.statusUrl" class="cpf-input mono" placeholder="https://mysite.com/api/status" />
            </div>
          </div>
          <label class="cpf-field">
            <span class="cpf-label">请求体（JSON，GET 可留空）</span>
            <input v-model="create.statusBody" class="cpf-input mono" placeholder='{} 或 {"req_source": 1}' />
          </label>
          <div class="cpf-field">
            <span class="cpf-label">怎么判断已领过</span>
            <div class="cpf-row">
              <select v-model="create.judgeMode" class="cpf-input cpf-input--mode">
                <option value="code">看业务码</option>
                <option value="bool">看布尔字段</option>
              </select>
              <input v-if="create.judgeMode === 'code'" v-model="create.codePath" class="cpf-input mono"
                placeholder="code_path，如 code" />
              <input v-if="create.judgeMode === 'code'" v-model="create.expectOk"
                class="cpf-input mono cpf-input--expect" placeholder="0" />
              <input v-else v-model="create.checkedInPath" class="cpf-input mono" placeholder="data.checked_in" />
            </div>
            <span class="cpf-hint">
              看业务码：响应里 code_path 的值等于期望值即「已领过」；看布尔字段：checked_in_path 为 true 即「已领过」
            </span>
          </div>
        </div>
      </section>

      <section class="cpf-sec">
        <div class="cpf-sec-head">
          <h3 class="cpf-sec-title">领取请求</h3>
        </div>
        <div class="cpf-stack">
          <div class="cpf-field">
            <span class="cpf-label">请求</span>
            <div class="cpf-row">
              <select v-model="create.claimMethod" class="cpf-input cpf-input--method">
                <option value="POST">POST</option>
                <option value="GET">GET</option>
              </select>
              <input v-model="create.claimUrl" class="cpf-input mono" placeholder="https://mysite.com/api/claim" />
            </div>
          </div>
          <label class="cpf-field">
            <span class="cpf-label">请求体（JSON，GET 可留空）</span>
            <input v-model="create.claimBody" class="cpf-input mono" placeholder='{} 或 {"req_source": 1}' />
          </label>
        </div>
      </section>

      <section class="cpf-sec">
        <div class="cpf-sec-head">
          <h3 class="cpf-sec-title">调度执行时间</h3>
        </div>
        <ScheduleTimesField v-model="create.times" :busy="saving" />
      </section>
    </template>

    <template v-else-if="platform">
      <section class="cpf-sec">
        <div class="cpf-sec-head">
          <h3 class="cpf-sec-title">可编辑信息</h3>
        </div>
        <div class="cpf-cols">
          <label class="cpf-field">
            <span class="cpf-label">平台名称</span>
            <input v-model="editName" class="cpf-input" maxlength="40" :disabled="saving" />
          </label>
          <div class="cpf-field">
            <span class="cpf-label">启用状态</span>
            <label class="pf-toggle">
              <input v-model="editActive" type="checkbox" :disabled="saving" />
              <span>{{ editActive ? "启用" : "已停用" }}</span>
            </label>
          </div>
        </div>
        <div class="cpf-field pf-schedule">
          <span class="cpf-label">调度执行时间</span>
          <ScheduleTimesField v-model="editTimes" :busy="saving" />
          <span v-if="platform.schedule_overridden || !platform.name_is_default" class="pf-reset">
            <button v-if="platform.schedule_overridden" class="btn btn--ghost" :disabled="saving"
              @click="resetSchedule">恢复平台默认调度</button>
            <button v-if="!platform.name_is_default" class="btn btn--ghost" :disabled="saving"
              @click="resetName">恢复默认名</button>
          </span>
        </div>
      </section>

    </template>

    <p v-if="error" class="cpf-err" role="alert">{{ error }}</p>

    <template #footer>
      <span class="cpf-foot-actions">
        <button class="btn btn--ghost" :disabled="saving" @click="emit('close')">取消</button>
        <button class="btn btn--primary" :disabled="saving || !canSave" @click="submit">
          {{ saving ? "保存中…" : isEdit ? "保存修改" : "保存并热加载" }}
        </button>
      </span>
    </template>
  </ModalShell>
</template>

<style scoped>
.cpf-sec {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 0;
  border-top: 1px solid var(--color-border);
}

.cpf-sec:first-child {
  padding-top: 0;
  border-top: 0;
}

.cpf-sec-head {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.cpf-sec-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.cpf-cols {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 20px;
  align-items: start;
}

.cpf-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.cpf-field {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 5px;
  min-width: 0;
  padding: 0;
  border: 0;
}

.cpf-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.cpf-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0;
  border: 0;
}

.cpf-input {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 7px 10px;
  font-size: var(--text-sm);
  color: var(--color-text);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.cpf-row>.cpf-input:not(.cpf-input--method):not(.cpf-input--mode):not(.cpf-input--expect) {
  flex: 1 1 auto;
}

.cpf-input--method {
  flex: 0 0 76px;
  width: 76px;
}

.cpf-input--mode {
  flex: 0 0 104px;
  width: 104px;
}

.cpf-input--expect {
  flex: 0 0 72px;
  width: 72px;
}

.cpf-hint {
  font-size: var(--text-xs);
  line-height: 1.55;
  color: var(--color-text-faint);
}

.cpf-hint--bad {
  color: var(--color-danger);
}

.cpf-err {
  margin: 12px 0 0;
  font-size: var(--text-xs);
  color: var(--color-danger);
}

.cpf-foot-actions {
  display: inline-flex;
  gap: var(--space-2);
  margin-left: auto;
}

.pf-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  font-size: var(--text-sm);
}

.pf-toggle span {
  display: inline-block;
  min-width: 3em;
}

.pf-schedule {
  margin-top: 16px;
}

.pf-reset {
  display: inline-flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

@media (max-width: 640px) {
  .cpf-cols {
    grid-template-columns: 1fr;
  }
}
</style>
