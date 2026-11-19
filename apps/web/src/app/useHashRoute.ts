/**
 * hash 路由域（conventions/4 §2.4，业务子域分包 2026-11-14）：
 * 页面状态的唯一持有者——可直链、可后退；旧直链命中别名即 replaceState
 * 静默重写为规范 hash（ADR-010 重定向表 v2，7 条）。
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import type { PageName } from "@/shared/types";

const hashByPage: Record<PageName, string> = {
  签到概览: "dashboard",  /* 显示名 2026-11-19 改为「签到概览」，hash 仍 dashboard 保收藏夹兼容 */
  平台管理: "platforms",
  账户管理: "accounts",
  用量管理: "traffic",
  运行日志: "logs",
  系统设置: "settings",
};
/* 旧直链兼容：四页时代规范链与新六页同在本表，命中即静默重写 */
const legacyHashByPage: Record<string, PageName> = {
  home: "签到概览",
  alerts: "签到概览",
  wallet: "账户管理",
  card: "账户管理",
  radar: "用量管理",
  usage: "用量管理",
  log: "运行日志",
};
const pageByHash = {
  ...Object.fromEntries(Object.entries(hashByPage).map(([page, hash]) => [hash, page])),
  ...legacyHashByPage,
} as Record<string, PageName>;

function resolveActive(): PageName {
  const hash = location.hash.slice(2);
  const page = pageByHash[hash] ?? "签到概览";
  if (pageByHash[hash] && hash !== hashByPage[page]) {
    history.replaceState(null, "", `#/${hashByPage[page]}`);
  }
  return page;
}

export function useHashRoute() {
  const active = ref<PageName>(resolveActive());

  function onHashChange() {
    const hash = location.hash.slice(2);
    const page = pageByHash[hash];
    if (!page) return;
    /* 运行中命中旧链也要静默重写（直链/收藏夹/脚本改 hash 都覆盖） */
    if (hash !== hashByPage[page]) {
      history.replaceState(null, "", `#/${hashByPage[page]}`);
    }
    active.value = page;
  }

  function navigate(page: PageName) {
    if (location.hash !== `#/${hashByPage[page]}`) location.hash = `#/${hashByPage[page]}`;
    active.value = page;
  }

  onMounted(() => {
    if (!location.hash) history.replaceState(null, "", `#/${hashByPage[active.value]}`);
    window.addEventListener("hashchange", onHashChange);
  });
  onBeforeUnmount(() => window.removeEventListener("hashchange", onHashChange));

  return { active, navigate };
}
