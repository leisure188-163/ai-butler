/**
 * hash 路由域（conventions/04 §2.4，业务子域分包 2026-11-14）：
 * 页面状态的唯一持有者——可直链、可后退；旧直链（#/home、#/wallet、#/card、
 * #/alerts、#/radar）命中别名即 replaceState 静默重写为规范 hash（ADR-009）。
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import type { PageName } from "../types";

const hashByPage: Record<PageName, string> = {
  账号: "accounts",
  用量: "usage",
  记录: "log",
  设置: "settings",
};
/* 旧直链兼容（矩阵改版）：别名命中即 replaceState 重写为规范 hash */
const legacyHashByPage: Record<string, PageName> = {
  home: "账号",
  wallet: "账号",
  card: "账号",
  alerts: "账号",
  radar: "用量",
};
const pageByHash = {
  ...Object.fromEntries(Object.entries(hashByPage).map(([page, hash]) => [hash, page])),
  ...legacyHashByPage,
} as Record<string, PageName>;

function resolveActive(): PageName {
  const hash = location.hash.slice(2);
  const page = pageByHash[hash] ?? "账号";
  if (pageByHash[hash] && hash !== hashByPage[page]) {
    history.replaceState(null, "", `#/${hashByPage[page]}`);
  }
  return page;
}

export function useHashRoute() {
  const active = ref<PageName>(resolveActive());

  function onHashChange() {
    const page = pageByHash[location.hash.slice(2)];
    if (page) active.value = page;
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
