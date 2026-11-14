<script setup lang="ts">
/**
 * 常驻待办栏（ADR-013 迁入仪表盘）：「AI 智能助手管家」叙事的落点。
 * 三节聚合语义沿用旧提醒页口径（待处理/到期规则不发明新值）：
 * - 已自动完成：今日自动巡检一句话（数据由壳组装；系统只汇报真做过的动作）
 * - 需要你处理：pending runs + 人话原因 + 证据折叠 + 能力驱动的领取按钮
 * - 即将到期：signal=notice 的凭据 + 有效期
 * 空态诚实：「没有需要你操心的事。」
 */
import { computed } from "vue";
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
}>();

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
          </div>
          <span class="tag" :class="`tag--${item.signal}`">{{ signalText(item.signal) }}</span>
          <button
            v-if="claimable.has(item.target)"
            class="btn btn--ghost"
            @click="emit('claim', item.target)"
          >领取</button>
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
          <button class="btn btn--ghost" @click="emit('navigate', '账户')">去账户</button>
        </li>
      </ul>
      <p v-else class="quietline">暂无临期凭据。</p>
    </section>

    <p v-if="nothingTodo" class="quietline">没有需要你操心的事。</p>
  </aside>
</template>
