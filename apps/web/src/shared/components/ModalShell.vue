<script setup lang="ts">
/**
 * 弹层外壳（2026-11-18）：新增/修改一律走弹出界面，不再往页面里塞内联表单。
 *
 * 纪律：只有壳（遮罩 / 卡片 / 标题 / 关闭 / Esc / 滚动锁 / 焦点约束），
 * 业务字段由调用方通过两个 slot 提供；颜色字号全部走 token。
 */
import { onBeforeUnmount, onMounted } from "vue";

const props = defineProps<{
  title: string;
  subtitle?: string;
  /** true = 有未保存操作，禁止点遮罩/Esc 关闭（避免误丢输入） */
  busy?: boolean;
}>();

const emit = defineEmits<{ close: [] }>();

function requestClose(): void {
  if (props.busy) return;
  emit("close");
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape") requestClose();
}

let previousOverflow = "";

onMounted(() => {
  previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  window.addEventListener("keydown", onKey);
});

onBeforeUnmount(() => {
  document.body.style.overflow = previousOverflow;
  window.removeEventListener("keydown", onKey);
});
</script>

<template>
  <Teleport to="body">
    <div class="scrim" role="presentation" @click.self="requestClose">
      <section class="dialog" role="dialog" aria-modal="true" :aria-label="title">
        <header class="dialog-head">
          <div>
            <h2 class="dialog-title">{{ title }}</h2>
            <p v-if="subtitle" class="dialog-sub">{{ subtitle }}</p>
          </div>
          <button class="btn btn--ghost" :disabled="busy" @click="requestClose">关闭</button>
        </header>
        <div class="dialog-body">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="dialog-foot">
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--color-scrim);
  backdrop-filter: blur(2px);
  overflow: auto;
}
.dialog {
  width: min(720px, 100%);
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md, 10px);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}
.dialog-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--color-border);
}
.dialog-title {
  margin: 0;
  font-size: 16px;
  color: var(--color-text);
}
.dialog-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--color-text-muted);
  max-width: 60ch;
}
.dialog-body {
  padding: 16px 20px;
  overflow: auto;
}
.dialog-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-2);
}
@media (max-width: 640px) {
  .scrim {
    padding: 0;
    align-items: stretch;
  }
  .dialog {
    width: 100%;
    max-height: none;
    height: 100%;
    border-radius: 0;
    border: 0;
  }
  .dialog-foot {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
