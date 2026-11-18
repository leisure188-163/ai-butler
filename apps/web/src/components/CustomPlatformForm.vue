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
    subtitle="内置清单之外的网站也能每日自动领取：登录态取自本机 Chrome，填好状态查询与领取请求即可。"
    :busy="props.saving"
    @close="emit('close')"
  >
    <section class="cpf-sec">
      <div class="cpf-sec-head">
        <h3 class="cpf-sec-title">基本信息</h3>
        <p class="cpf-sec-sub">平台编码同时用作调度与台账的 key，建好后不再改。</p>
      </div>
      <div class="cpf-cols">
        <label class="cpf-field">
          <span class="cpf-label">平台编码</span>
          <input v-model="form.code" class="cpf-input mono" placeholder="mysite" />
          <span class="cpf-hint" :class="{ 'cpf-hint--bad': form.code && !codeOk }">
            小写字母开头，仅 a-z / 0-9 / _，2–32 位
          </span>
        </label>
        <label class="cpf-field">
          <span class="cpf-label">平台名称</span>
          <input v-model="form.display" class="cpf-input" placeholder="My Site" />
          <span class="cpf-hint">列表与台账里显示的名字</span>
        </label>
        <label class="cpf-field">
          <span class="cpf-label">登录域名</span>
          <input v-model="form.domain" class="cpf-input mono" placeholder="mysite.com" />
          <span class="cpf-hint">用于在本机 Chrome 的 cookie 库里匹配站点</span>
        </label>
        <label class="cpf-field">
          <span class="cpf-label">登录态 cookie 名</span>
          <input v-model="form.cookies" class="cpf-input mono" placeholder="sessionid, token" />
          <span class="cpf-hint">逗号分隔；这些 cookie 全在才算已登录</span>
        </label>
      </div>
    </section>

    <section class="cpf-sec">
      <div class="cpf-sec-head">
        <h3 class="cpf-sec-title">状态查询</h3>
        <p class="cpf-sec-sub">先问「今天领过没」，已领过就不再发领取请求。</p>
      </div>
      <div class="cpf-stack">
        <div class="cpf-field">
          <span class="cpf-label">请求</span>
          <div class="cpf-row">
            <select v-model="form.statusMethod" class="cpf-input cpf-input--method">
              <option value="GET">GET</option>
              <option value="POST">POST</option>
            </select>
            <input
              v-model="form.statusUrl"
              class="cpf-input mono"
              placeholder="https://mysite.com/api/status"
            />
          </div>
        </div>
        <label class="cpf-field">
          <span class="cpf-label">请求体（JSON，GET 可留空）</span>
          <input
            v-model="form.statusBody"
            class="cpf-input mono"
            placeholder='{} 或 {"req_source": 1}'
          />
        </label>
        <div class="cpf-field">
          <span class="cpf-label">怎么判断已领过</span>
          <div class="cpf-row">
            <select v-model="form.judgeMode" class="cpf-input cpf-input--mode">
              <option value="code">看业务码</option>
              <option value="bool">看布尔字段</option>
            </select>
            <input
              v-if="form.judgeMode === 'code'"
              v-model="form.codePath"
              class="cpf-input mono"
              placeholder="code_path，如 code"
            />
            <input
              v-if="form.judgeMode === 'code'"
              v-model="form.expectOk"
              class="cpf-input mono cpf-input--expect"
              placeholder="0"
            />
            <input
              v-else
              v-model="form.checkedInPath"
              class="cpf-input mono"
              placeholder="data.checked_in"
            />
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
        <p class="cpf-sec-sub">真正签到的那一下；判定沿用上面的 code_path 与期望值。</p>
      </div>
      <div class="cpf-stack">
        <div class="cpf-field">
          <span class="cpf-label">请求</span>
          <div class="cpf-row">
            <select v-model="form.claimMethod" class="cpf-input cpf-input--method">
              <option value="POST">POST</option>
              <option value="GET">GET</option>
            </select>
            <input
              v-model="form.claimUrl"
              class="cpf-input mono"
              placeholder="https://mysite.com/api/claim"
            />
          </div>
        </div>
        <label class="cpf-field">
          <span class="cpf-label">请求体（JSON，GET 可留空）</span>
          <input
            v-model="form.claimBody"
            class="cpf-input mono"
            placeholder='{} 或 {"req_source": 1}'
          />
        </label>
      </div>
    </section>

    <section class="cpf-sec">
      <div class="cpf-sec-head">
        <h3 class="cpf-sec-title">调度</h3>
        <p class="cpf-sec-sub">可留空，接入后在名册里按平台修改。</p>
      </div>
      <label class="cpf-field">
        <span class="cpf-label">每日执行时间</span>
        <input v-model="form.scheduleTimes" class="cpf-input mono" placeholder="08:35, 20:35" />
        <span class="cpf-hint">HH:MM，逗号分隔；留空则只手动领取</span>
      </label>
    </section>

    <p v-if="error" class="cpf-err" role="alert">{{ error }}</p>

    <template #footer>
      <span class="cpf-foot-note">保存后自动热加载</span>
      <span class="cpf-foot-actions">
        <button class="btn btn--ghost" :disabled="props.saving" @click="emit('close')">取消</button>
        <button class="btn btn--primary" :disabled="props.saving || !canSave" @click="submit">
          {{ props.saving ? "保存中…" : "保存并热加载" }}
        </button>
      </span>
    </template>
  </ModalShell>
</template>

<style scoped>
/* 2026-11-18 重构：原版是 4 个字段 auto-fit 网格 + 两列并排接口块，列宽被内容拉扯、
   字段高度不一致、说明文字互相压字。现改成「分组 + 组内两列等宽 / 组内单列纵排」。
   注意：类名全部加 cpf- 前缀——全局 styles/ui.css 里有设置件 `.field`（flex + border-bottom）
   与列表行 `.row`，撞名会把表单染成一条条带下划线的横排。 */
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
.cpf-sec-sub {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--color-text-muted);
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
.cpf-row > .cpf-input:not(.cpf-input--method):not(.cpf-input--mode):not(.cpf-input--expect) {
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
.cpf-foot-note {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
}
.cpf-foot-actions {
  display: inline-flex;
  gap: var(--space-2);
  margin-left: auto;
}
@media (max-width: 640px) {
  .cpf-cols {
    grid-template-columns: 1fr;
  }
}
</style>
