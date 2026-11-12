<script setup lang="ts">
import { computed } from "vue";
import BizCard from "../components/BizCard.vue";
import type { AccountItem, AppItem, PageName, RunItem } from "../types";
import { earliestExpiry, faceOf, fmtTime } from "../utils";

const props = defineProps<{
  accounts: AccountItem[];
  apps: AppItem[];
  pending: RunItem[];
  loading: boolean;
  loadError: string;
}>();

const emit = defineEmits<{ navigate: [page: PageName] }>();

const headline = computed(() => {
  if (props.loading) return { strong: "正在打开卡包", tail: "正在拉取最新状态" };
  if (props.loadError) return { strong: "暂时够不到服务", tail: "确认 server 已启动后，到侧栏点刷新" };
  const n = props.pending.length;
  if (n > 0) return { strong: `${n} 项待处理`, tail: "处理完即可清静" };
  if (props.accounts.length === 0)
    return { strong: "卡包还是空的", tail: "去卡包页导入应用，第一张卡就位" };
  const unwell = props.accounts.filter((a) => a.signal !== "ok").length;
  if (unwell > 0)
    return { strong: `${props.accounts.length} 张卡，${unwell} 张需要留意`, tail: "卡面状态脊与灯即现状" };
  return { strong: `${props.accounts.length} 张卡状态正常`, tail: "今日无事" };
});

function issuerOf(account: AccountItem): string {
  return props.apps.find((x) => x.account_id === account.account_id)?.display ?? "未关联应用";
}
</script>

<template>
  <header class="head">
    <h1 class="page-title">{{ headline.strong }}</h1>
    <p class="page-sub">{{ headline.tail }}</p>
  </header>

  <section class="fan" aria-label="卡">
    <BizCard
      v-for="(account, i) in accounts"
      :key="account.account_id"
      :issuer="issuerOf(account)"
      :account-id="account.account_id"
      :signal="account.signal"
      :expires-at="earliestExpiry(account)"
      :face="faceOf(account.account_id)"
      reveal
      :style="{ '--i': i }"
      @activate="emit('navigate', '卡包')"
    />
    <button class="fan-add" @click="emit('navigate', '卡包')">
      <span class="fan-add-plus" aria-hidden="true">＋</span>
      导入应用
    </button>
  </section>

  <section class="section" aria-label="待处理">
    <h2 class="section-title">待处理</h2>
    <ul v-if="pending.length" class="rows panel">
      <li v-for="item in pending" :key="item.id" class="row">
        <span class="lamp" :class="`lamp--${item.signal}`" aria-hidden="true"></span>
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
        <span class="row-time">{{ fmtTime(item.started_at) }}</span>
      </li>
    </ul>
    <p v-else class="quietline">暂无待处理事项。</p>
  </section>
</template>

<style scoped>
.head { padding-top: var(--space-2); }

.fan {
  display: flex;
  align-items: flex-start;
  overflow-x: auto;
  padding: var(--space-6) var(--space-2) var(--space-4);
  margin: 0 calc(-1 * var(--space-2));
}
.fan > * { flex: none; }
.fan > * + * { margin-left: -26px; }
.fan > :nth-child(odd) { transform: rotate(-1.4deg); }
.fan > :nth-child(even) { transform: rotate(1.2deg); }
.fan > *:hover {
  transform: translateY(-8px) rotate(0deg);
  z-index: 3;
}

.fan-add {
  position: relative;
  box-sizing: border-box;
  width: 100%;
  max-width: 340px;
  aspect-ratio: 1.586;
  border: 1.5px dashed var(--color-border);
  border-radius: var(--radius-lg);
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-size: var(--text-sm);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  cursor: pointer;
  transition:
    border-color var(--motion-base),
    color var(--motion-base),
    transform var(--motion-base) var(--ease-out);
}
.fan-add:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}
.fan-add-plus { font-size: 20px; line-height: 1; }
</style>
