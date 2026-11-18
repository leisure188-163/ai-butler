<script setup lang="ts">
/**
 * 自定义平台表单（2026-11-18）：内置清单之外的平台由用户自建。
 * 2026-11-18 改版：从页面内联展开改为**弹出界面**（ModalShell）——新增/修改统一走弹层。
 *
 * 为什么不给 YAML 编辑器：新手看不懂五段式声明，所以这里只问 4 件人话的事
 * （是哪个网站 / 状态怎么问 / 领取怎么发 / 什么时候跑），由 server 渲染成
 * 与内置连接器同构的 manifest + 声明式 YAML。
 * 凭据固定走「本机 Chrome 登录态」（browser_cookie）——与内置网页连接器同一条链路。
 */
import { computed, reactive, ref } from "vue";
import ModalShell from "./ModalShell.vue";
import type { CustomPlatformDraft } from "../types";

const props = defineProps<{ saving: boolean }>();
const emit = defineEmits<{
  save: [draft: CustomPlatformDraft];
  close: [];
}>();

const form = reactive({
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
  scheduleTimes: "",
});

const error = ref<string>("");

const codeOk = computed(() => /^[a-z][a-z0-9_]{1,31}$/.test(form.code.trim()));
const canSave = computed(
  () =>
    codeOk.value &&
    form.display.trim() !== "" &&
    form.domain.trim() !== "" &&
    form.cookies.trim() !== "" &&
    form.statusUrl.trim() !== "" &&
    form.claimUrl.trim() !== "",
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

function parseTimes(text: string): string[] {
  const items = text
    .split(/[,，\s]+/)
    .map((t) => t.trim())
    .filter(Boolean);
  for (const t of items) {
    if (!/^[0-2][0-9]:[0-5][0-9]$/.test(t)) throw new Error(`调度时间 ${t} 不是 HH:MM`);
  }
  return items;
}

function submit(): void {
  error.value = "";
  try {
    const draft: CustomPlatformDraft = {
      code: form.code.trim(),
      display: form.display.trim(),
      domain: form.domain.trim(),
      cookies: form.cookies
        .split(/[,，\s]+/)
        .map((c) => c.trim())
        .filter(Boolean),
      status: {
        request: {
          method: form.statusMethod as "GET" | "POST",
          url: form.statusUrl.trim(),
          body: parseBody(form.statusBody),
        },
        checked_in_path: form.judgeMode === "bool" ? form.checkedInPath.trim() : "",
        code_path: form.codePath.trim() || "code",
        expect_ok: form.expectOk.trim() || "0",
      },
      claim: {
        request: {
          method: form.claimMethod as "GET" | "POST",
          url: form.claimUrl.trim(),
          body: parseBody(form.claimBody),
        },
        code_path: form.codePath.trim() || "code",
        expect_ok: form.expectOk.trim() || "0",
        retry_on_codes: [],
      },
      schedule_times: parseTimes(form.scheduleTimes),
    };
    emit("save", draft);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}
</script>

<template>
  <ModalShell
    title="自定义平台"
    subtitle="给内置清单之外的网站建一个能真跑的每日领取：登录态从本机 Chrome 抓，状态查询与领取请求由你填，服务端渲染成声明式连接器。"
    :busy="props.saving"
    @close="emit('close')"
  >
    <div class="grid">
      <label class="field">
        <span class="label">平台编码</span>
        <input v-model="form.code" class="input mono" placeholder="mysite" />
        <span class="hint" :class="{ 'hint--bad': form.code && !codeOk }">
          小写字母开头，仅 a-z/0-9/_，2-32 位；之后用它做调度与台账的 key
        </span>
      </label>
      <label class="field">
        <span class="label">平台名称</span>
        <input v-model="form.display" class="input" placeholder="My Site" />
      </label>
      <label class="field">
        <span class="label">登录域名</span>
        <input v-model="form.domain" class="input mono" placeholder="mysite.com" />
        <span class="hint">用于在本机 Chrome 的 cookie 库里匹配站点</span>
      </label>
      <label class="field">
        <span class="label">登录态 cookie 名</span>
        <input v-model="form.cookies" class="input mono" placeholder="sessionid, token" />
        <span class="hint">逗号分隔；这些 cookie 全在才算已登录</span>
      </label>
    </div>

    <div class="grid grid--two">
      <div class="field">
        <span class="label">状态查询（先问「今天领过没」）</span>
        <div class="row">
          <select v-model="form.statusMethod" class="input input--sm">
            <option value="GET">GET</option>
            <option value="POST">POST</option>
          </select>
          <input v-model="form.statusUrl" class="input mono" placeholder="https://mysite.com/api/status" />
        </div>
        <input v-model="form.statusBody" class="input mono" placeholder="请求体 JSON（可空）" />
        <div class="row">
          <select v-model="form.judgeMode" class="input input--sm">
            <option value="code">业务码</option>
            <option value="bool">布尔字段</option>
          </select>
          <input
            v-if="form.judgeMode === 'code'"
            v-model="form.codePath"
            class="input mono input--sm"
            placeholder="code"
          />
          <input
            v-if="form.judgeMode === 'code'"
            v-model="form.expectOk"
            class="input mono input--sm"
            placeholder="0"
          />
          <input
            v-else
            v-model="form.checkedInPath"
            class="input mono"
            placeholder="data.checked_in"
          />
        </div>
        <span class="hint">
          业务码模式：响应里 code_path 的值等于 expect_ok 即成功；
          布尔模式：checked_in_path 为 true 即今天已领过
        </span>
      </div>

      <div class="field">
        <span class="label">领取请求（真正签到那一下）</span>
        <div class="row">
          <select v-model="form.claimMethod" class="input input--sm">
            <option value="POST">POST</option>
            <option value="GET">GET</option>
          </select>
          <input v-model="form.claimUrl" class="input mono" placeholder="https://mysite.com/api/claim" />
        </div>
        <input v-model="form.claimBody" class="input mono" placeholder="请求体 JSON（可空）" />
        <span class="hint">判定与状态查询共用 code_path / expect_ok；领取受理后以状态复查为准</span>
      </div>
    </div>

    <label class="field">
      <span class="label">调度执行时间（可留空，之后在名册里改）</span>
      <input v-model="form.scheduleTimes" class="input mono" placeholder="08:35, 20:35" />
    </label>

    <p v-if="error" class="err" role="alert">{{ error }}</p>

    <template #footer>
      <span class="hint">
        保存后自动热加载；到名册里点「接入」，会从本机 Chrome 抓登录态并登记账户。
      </span>
      <span class="foot-actions">
        <button class="btn btn--ghost" :disabled="props.saving" @click="emit('close')">取消</button>
        <button class="btn btn--primary" :disabled="props.saving || !canSave" @click="submit">
          {{ props.saving ? "保存中…" : "保存并热加载" }}
        </button>
      </span>
    </template>
  </ModalShell>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px 16px;
  margin-bottom: 14px;
}
.grid--two {
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
}
.field {
  display: grid;
  gap: 5px;
  min-width: 0;
  margin-bottom: 12px;
}
.label {
  font-size: 12px;
  color: var(--color-text-muted);
}
.row {
  display: flex;
  gap: 6px;
  align-items: center;
}
.input {
  min-width: 0;
  width: 100%;
  padding: 6px 9px;
  font-size: 13px;
  color: var(--color-text);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}
.input--sm {
  flex: 0 0 auto;
  width: auto;
}
.hint {
  font-size: 11px;
  color: var(--color-text-muted);
  line-height: 1.5;
}
.hint--bad {
  color: var(--color-danger);
}
.err {
  margin: 0;
  font-size: 12px;
  color: var(--color-danger);
}
.foot-actions {
  display: inline-flex;
  gap: 8px;
}
@media (max-width: 640px) {
  .grid,
  .grid--two {
    grid-template-columns: 1fr;
  }
}
</style>
