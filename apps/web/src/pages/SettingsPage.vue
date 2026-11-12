<script setup lang="ts">
import type { Settings } from "../types";

defineProps<{
  settings: Settings;
  serverInfo: { title: string; version: string } | null;
}>();

const emit = defineEmits<{ update: [patch: Partial<Settings>] }>();

function onIntervalChange(event: Event) {
  emit("update", { intervalSec: Number((event.target as HTMLSelectElement).value) });
}
</script>

<template>
  <header class="head">
    <h1 class="page-title">设置</h1>
    <p class="page-sub">改动即时生效，保存在本机浏览器。</p>
  </header>

  <section class="section" aria-label="通用">
    <h2 class="section-title">通用</h2>
    <div class="panel">
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
    <div class="panel">
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

  <section class="section" aria-label="关于">
    <h2 class="section-title">关于</h2>
    <div class="panel">
      <div class="field">
        <span class="field-label">产品</span>
        <span class="field-value">Kabao（卡包）· 本地优先的 AI 账号管家</span>
      </div>
      <div class="field">
        <span class="field-label">版本</span>
        <span class="field-value mono">
          {{ serverInfo ? `${serverInfo.title} ${serverInfo.version}` : "—" }}
        </span>
      </div>
      <div class="field">
        <span class="field-label">数据位置</span>
        <span class="field-value">kabao.db（平台标准数据根）</span>
      </div>
      <div class="field">
        <span class="field-label">仓库</span>
        <a
          class="field-link"
          href="https://gitee.com/hiclaw_520/ai-marina"
          target="_blank"
          rel="noreferrer"
        >gitee.com/hiclaw_520/ai-marina</a>
      </div>
      <div class="field">
        <span class="field-label">接口文档</span>
        <a
          class="field-link"
          href="http://127.0.0.1:8000/docs"
          target="_blank"
          rel="noreferrer"
        >127.0.0.1:8000/docs</a>
      </div>
    </div>
  </section>
</template>

<style scoped>
.head { padding-top: var(--space-2); }
.section .quietline { margin-top: var(--space-2); }
</style>
