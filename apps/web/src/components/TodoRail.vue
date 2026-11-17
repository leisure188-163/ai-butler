<script setup lang="ts">
/**
 * 常驻待办栏（ADR-010 迁入仪表盘）：「AI 智能助手管家」叙事的落点。
 * 三节聚合语义沿用旧提醒页口径（待处理/到期规则不发明新值）：
 * - 已自动完成：今日自动巡检一句话（数据由壳组装；系统只汇报真做过的动作）
 * - 需要你处理：pending runs + 人话原因 + 证据折叠 + 能力驱动的领取按钮
 * - 即将到期：signal=notice 的凭据 + 有效期
 * 空态诚实：「没有需要你操心的事。」
 */
import { computed, ref } from "vue";
import type { AccountItem, CredentialItem, PageName, RunItem } from "../types";
import { fmtTime, signalText } from "../utils";

const props = defineProps<{
  pending: RunItem[];
  accounts: AccountItem[];
  /** 今日自动巡检一句话数据（壳组装；今日无体检类 runs → null） */
  todayDone: { label: string; ok: number; total: number } | null;
  /** 可领取的 target 集合（壳按 capabilities.provision.run 组装，端零映射） */
  claimable: Set<string>;
}>();

const emit = defineEmits<{
  navigate: [page: PageName];
  claim: [target: string];
  repair: [target: string, accountId: string];
}>();

/* ---- 修复入口（ADR-015）：待办行内展开「重新登录 → 我已登录，重试」----
 * 只做引导与发起：登录动作永远由用户在客户端完成（切号/登录不自动化）。 */
const repairingId = ref<string | null>(null);

function openRepair(item: RunItem) {
  repairingId.value = item.id;
}

function confirmRepair(item: RunItem) {
  repairingId.value = null;
  emit("repair", item.target, item.account_id);
}

function repairLabel(actionId: string | null | undefined): string {
  return actionId === "relogin" ? "重新登录" : "重新扫描";
}

/* 即将到期 = signal=notice 的凭据（旧提醒页同口径） */
const expiring = computed<{ account: AccountItem; cred: CredentialItem }[]>(() =>
  props.accounts.flatMap((account) =>
    account.credentials
      .filter((c) => c.signal === "notice")
      .map((cred) => ({ account, cred })),
  ),
);

const nothingTodo = computed(() => !props.pending.length && !expiring.value.length);
</script>

<template>
  <aside class="rail" aria-label="待办">
    <section>
      <p class="rail-title">已自动完成</p>
      <p class="quietline">
        {{
          todayDone
            ? `今日已自动处理 ${todayDone.label}：${todayDone.ok}/${todayDone.total} 正常`
            : "今日自动巡检尚未运行。"
        }}
      </p>
    </section>

    <section>
      <p class="rail-title">需要你处理（{{ pending.length }}）</p>
      <ul v-if="pending.length" class="rows sheet">
        <li v-for="item in pending" :key="item.id" class="row">
          <div class="row-main">
            <p class="row-title">
              {{ item.account_id }}
              <span class="row-sub mono">{{ item.kind }} · {{ item.target }}</span>
            </p>
            <p v-if="item.repair_reason" class="row-fix">{{ item.repair_reason }}</p>
            <details v-if="item.evidence.length" class="fold">
              <summary>查看详情</summary>
              <ul class="evidence">
                <li v-for="(ev, j) in item.evidence" :key="j">
                  {{ ev.summary }}<code v-if="ev.raw_code"> [{{ ev.raw_code }}]</code>
                </li>
              </ul>
            </details>
            <div v-if="repairingId === item.id" class="repair-panel">
              <p class="repair-steps">
                1. 在 {{ item.target }} 客户端退出登录，再重新登录<br />
                2. 回到这里点「我已登录，立即重试」——会先重新读取本机凭据
              </p>
              <div class="repair-actions">
                <button class="btn btn--primary" @click="confirmRepair(item)">
                  我已登录，立即重试
                </button>
                <button class="btn btn--ghost" @click="repairingId = null">取消</button>
              </div>
            </div>
          </div>
          <span class="tag" :class="`tag--${item.signal}`">{{ signalText(item.signal) }}</span>
          <div class="row-actions">
            <button
              v-if="item.repair_action_id"
              class="btn btn--ghost"
              @click="openRepair(item)"
            >{{ repairLabel(item.repair_action_id) }}</button>
            <button
              v-if="claimable.has(item.target)"
              class="btn btn--ghost"
              @click="emit('claim', item.target)"
            >领取</button>
          </div>
        </li>
      </ul>
      <p v-else class="quietline">暂无待处理事项。</p>
    </section>

    <section>
      <p class="rail-title">即将到期（{{ expiring.length }}）</p>
      <ul v-if="expiring.length" class="rows sheet">
        <li
          v-for="{ account, cred } in expiring"
          :key="`${account.account_id}-${cred.kind}`"
          class="row"
        >
          <div class="row-main">
            <p class="row-title">{{ account.account_id }}</p>
            <p class="row-sub">
              {{ cred.kind }} · 有效期至 <span class="num">{{ fmtTime(cred.expires_at) }}</span>
            </p>
          </div>
          <span class="tag tag--notice">{{ signalText(cred.signal) }}</span>
          <button class="btn btn--ghost" @click="emit('navigate', '账户管理')">去账户</button>
        </li>
      </ul>
      <p v-else class="quietline">暂无临期凭据。</p>
    </section>

    <p v-if="nothingTodo" class="quietline">没有需要你操心的事。</p>
  </aside>
</template>

<style scoped>
.repair-panel {
  margin-top: var(--space-2);
  padding: var(--space-3);
  background: var(--color-surface-2);
  border-radius: var(--radius-sm);
}
.repair-steps {
  margin: 0 0 var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  line-height: 1.5;
}
.repair-actions { display: flex; gap: var(--space-2); }
</style>
