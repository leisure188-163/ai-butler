# web 端模式（apps/web，Vue3 + TS）

## 1. 类型：契约派生，禁手写（红线 4）

`apps/web/src/types.ts:10-37`：

```ts
type Contract = components["schemas"];          // 来自 @butler/sdk gen
type WithSignal<T> = Omit<T, "signal"> & { signal: Signal };
```

- 一切 DTO 从 `@butler/sdk` 生成物派生；唯一允许的本地加工 = signal 窄化（端零映射）
- 新端点字段 = 先 `pnpm gen:sdk`，再在 types.ts 加派生类型

## 2. api.ts：端点单源，按域分节

`apps/web/src/api.ts:20-102`：

```ts
/* ---- 用量域 ---- */
export async function getRadar(): Promise<RadarAccount[]> { ... }
```

- 按 server 四域分节注释，新端点归入对应节；域不存在则新开节
- 私有 `request<T>` 非 2xx 抛 `ApiError`
- **容错语义随函数走并写注释**：哪些函数永不 throw（如 `getRadar` 采集未跑 = 空数据合法）、哪些原样上抛（红线 5）

## 3. composables：动作下沉，按域分文件

`apps/web/src/composables/useAccountActions.ts:13-43`：

```ts
export function useAccountActions({ refresh }: { refresh: () => Promise<void> }) {
  const busyTarget = ref<string | null>(null);
  const actionMsg = ref<{ text: string; kind: "ok" | "warn" } | null>(null);
  ...
}
```

- `busyTarget/actionMsg` 这类状态归本域 composable，不进全局
- `ApiError` 转 UI 文案；网络异常原样 re-throw（红线 5）

## 4. 页面/组件

- Vue3 `<script setup lang="ts">`；`defineProps<{...}>()` 类型字面量、`defineEmits<{...}>()`
- 页面只做页头与动作下发，交互下沉子组件（`AccountsPage.vue:11-33`）
- 展示分类只消费 core 出产谓词（signal 五分类、`quota_low`），**禁止自造阈值判断**（红线 2）

## 5. 样式：token 闭合 + BEM

- 颜色/字号/间距一律 `var(--token)`；token 唯一来源 `styles/tokens.css`（红线 6，机检）
- 通用类进 `styles/ui.css`，BEM 变体命名：`.btn--primary`、`.kpi-value--ok`、`.cal-dot--ok`
- 布局类由各组件 `<style scoped>` 自持，颜色字号仍引 token
- 不引图表/UI 库——图形化用内联 SVG/CSS 零依赖（先例：仪表盘日历条带/水位条）

## 6. 注意

- `apps` 数据键是 `id`（不是 `app_id`/`target`）；账号是 `account_id`——以 sdk 生成类型为准，别凭记忆
- dev server：`pnpm dev:web`；类型检查：`pnpm --dir apps/web exec vue-tsc --noEmit`
- 路由 hash 直链不变（ADR-010 六页 IA）；侧栏分组属纯视觉层
