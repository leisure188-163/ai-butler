<script setup lang="ts">
/**
 * 未导入的平台（2026-11-19 用户裁决，[ADR-032]）：同步平台只自动纳本机客户端，
 * 网页版等被策略跳过的连接器留在这里，由用户按需「导入」——点一下即纳册 + 接入。
 *
 * 2026-11-19 五次改版：用户要求把页头「同步平台」归到本区块，命名为「扫描本机」——
 * 它做的就是这个区块的来源：扫本机连接器、把客户端写进名册，网页版留在下面手动导入。
 * 区块不再因空清单隐藏（扫描入口必须始终可达；名册被清空后正需要它）。
 *
 * 版式（2026-11-19 四次改版）：用户嫌整宽长条行「难看、占空间」，要求改成卡片——
 * 自适应网格（宽屏一行 4~5 枚、窄屏 2 枚），每枚卡片只有官方图标 + display 名称，
 * 整卡即导入按钮（hover 出主色 + ＋），编码 / 类型 / 注释全部不显示。
 */
import { ref } from "vue";

import PlatformBadge from "./PlatformBadge.vue";
import type { PlatformCandidate } from "../types";
import { faceOf } from "../utils";
import { platformIcon } from "../utils/platformIcons";

const props = defineProps<{
  candidates: PlatformCandidate[];
  busy: boolean;
  /** 正在扫描本机连接器（busyTarget === "resync"） */
  scanning: boolean;
}>();
const emit = defineEmits<{ adopt: [code: string]; resync: [] }>();

const open = ref(false); // 2026-11-19 用户裁决：默认收起，需要时再展开
</script>

<template>
  <section class="pending sheet" aria-label="未导入的平台">
    <header class="pending-head">
      <div
        class="pending-head-main"
        role="button"
        tabindex="0"
        :aria-expanded="open"
        aria-controls="pending-grid"
        @click="open = !open"
        @keydown.enter.prevent="open = !open"
        @keydown.space.prevent="open = !open"
      >
        <h3 class="pending-title">
          未导入的平台
          <span class="pending-count">{{ props.candidates.length }}</span>
        </h3>
        <span class="pending-caret" :class="{ 'pending-caret--open': open }" aria-hidden="true">
          <svg viewBox="0 0 16 16" width="12" height="12">
            <path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.5" fill="none" />
          </svg>
        </span>
      </div>
      <div class="pending-actions">
        <button
          class="btn btn--ghost pending-scan"
          :disabled="props.busy || props.scanning"
          title="扫描本机客户端：刷新平台名册并自动接入已登录的客户端账户；网页版仍在这里手动导入"
          @click="emit('resync')"
        >
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
            <path
              d="M13 8a5 5 0 1 1-1.5-3.6M13 3v3.5H9.5"
              stroke="currentColor"
              stroke-width="1.4"
              fill="none"
            />
          </svg>
          {{ props.scanning ? "扫描中…" : "扫描本机" }}
        </button>
      </div>
    </header>
    <ul v-if="open" id="pending-grid" class="pending-grid">
      <li v-for="candidate in props.candidates" :key="candidate.platform_code">
        <button
          class="pending-card"
          :title="`导入 ${candidate.platform_name}`"
          :aria-label="`导入 ${candidate.platform_name}`"
          :disabled="props.busy"
          @click="emit('adopt', candidate.platform_code)"
        >
          <PlatformBadge
            :name="candidate.platform_name"
            :color-index="faceOf(candidate.platform_code)"
            :icon="platformIcon({ id: candidate.platform_code })"
            size="sm"
          />
          <span class="pending-add" aria-hidden="true">
            <svg viewBox="0 0 16 16" width="12" height="12">
              <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" fill="none" />
            </svg>
          </span>
        </button>
      </li>
    </ul>
    <p v-if="open && !props.candidates.length" class="pending-empty">本机连接器都已在名册里</p>
  </section>
</template>

<style scoped>
.pending {
  margin-top: var(--space-4);
  padding: 0 var(--space-4);
}
.pending-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
}
/* 栏目本身可点（2026-11-19 用户裁决）：点标题 / 计数 / 箭头任意一处都能展开或收起；
   右侧「扫描本机」是独立按钮，不参与折叠。 */
.pending-head-main {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.pending-head-main:hover .pending-caret { color: var(--color-accent); }
.pending-head-main:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
.pending-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-ink);
}
.pending-count {
  min-width: 20px;
  padding: 1px 6px;
  border-radius: var(--radius-chip);
  background: var(--color-quiet-weak);
  color: var(--color-quiet-ink);
  font-size: var(--text-xs);
  font-weight: 400;
  text-align: center;
}
.pending-actions { display: flex; align-items: center; gap: var(--space-3); }
.pending-scan {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: var(--text-xs);
}
.pending-empty {
  margin: 0;
  padding: 10px 0;
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}
.pending-caret {
  display: inline-flex;
  color: var(--color-text-muted);
  transition: transform 0.16s ease;
}
.pending-caret--open { transform: rotate(180deg); }
.pending-grid {
  list-style: none;
  margin: 0;
  padding: 8px 0 10px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 8px;
}
.pending-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-2);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.pending-card:hover:not(:disabled) {
  border-color: var(--color-accent);
  background: var(--color-accent-weak);
}
.pending-card:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
.pending-card:disabled { opacity: 0.55; cursor: not-allowed; }
.pending-card :deep(.badge) { flex: 1; min-width: 0; }
.pending-add {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: var(--radius-chip);
  color: var(--color-text-faint);
}
.pending-card:hover:not(:disabled) .pending-add { color: var(--color-accent); }
</style>
