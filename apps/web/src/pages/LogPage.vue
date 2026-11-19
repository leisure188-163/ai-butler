<script setup lang="ts">
import type { RunItem } from "../types";
import { fmtTime } from "../utils";

defineProps<{ runs: RunItem[] }>();
</script>

<template>
  <header class="head">
    <h1 class="page-title">运行日志</h1>
    <p class="page-sub">操作台账——每次动作都留痕。</p>
  </header>

  <section class="section" aria-label="动作日志">
    <div class="log-wrap sheet">
      <table class="log">
        <thead>
          <tr><th>时间</th><th>动作</th><th>平台</th><th>账户</th><th>结果</th></tr>
        </thead>
        <tbody>
          <tr v-if="!runs.length">
            <td class="table-empty" colspan="5">
              暂无运行记录——动作执行后会在这里留痕。
            </td>
          </tr>
          <tr v-for="run in runs" :key="run.id">
            <td class="num">{{ fmtTime(run.started_at) }}</td>
            <td class="mono code">{{ run.kind }}</td>
            <td>{{ run.target }}</td>
            <td class="mono code">{{ run.account_id }}</td>
            <td>
              <span class="tag" :class="`tag--${run.signal}`">{{ run.status ?? "…" }}</span>
              <details v-if="run.evidence.length" class="fold fold--inline">
                <summary>详情</summary>
                <ul class="evidence">
                  <li v-for="(ev, i) in run.evidence" :key="i">
                    {{ ev.summary }}<code v-if="ev.raw_code"> [{{ ev.raw_code }}]</code>
                  </li>
                </ul>
              </details>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.head { padding-top: var(--space-2); }

.log-wrap { overflow-x: auto; }
.log { width: 100%; min-width: 560px; border-collapse: collapse; font-size: var(--text-sm); }
.log th {
  text-align: left;
  font-weight: 600;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  background: var(--color-surface-2);
  border-bottom: 1px solid var(--color-border);
  padding: var(--space-2) var(--space-4);
  white-space: nowrap;
}
.log td {
  border-bottom: 1px solid var(--color-border);
  padding: var(--space-3) var(--space-4);
  vertical-align: top;
}
.log tr:last-child td { border-bottom: none; }
.code { font-size: var(--text-xs); }
.fold--inline { margin-top: var(--space-2); }
</style>
