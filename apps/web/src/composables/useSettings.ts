/**
 * 设置域（conventions/4 §2.4，业务子域分包 2026-11-14）：
 * 本机浏览器持久化（butler.settings.v1）+ 主题应用（<html data-theme>）+ 系统跟随。
 * 注意：THEME_NAMES 必须先于 loadSettings() 调用点声明（函数声明提升、const 不提升，
 * 否则 has() 进 TDZ 抛错被 try/catch 静默吞掉，存档主题永远回退 system）。
 */
import { onBeforeUnmount, ref, watch } from "vue";
import type { Settings, ThemeName } from "../types";

const THEME_NAMES: ReadonlySet<string> = new Set(["system", "paper", "dark", "warm"]);

export function useSettings() {
  const settings = ref<Settings>(loadSettings());

  function loadSettings(): Settings {
    try {
      let raw = localStorage.getItem("butler.settings.v1");
      if (!raw) {
        /* 一次性迁移（A1-03 §7）：旧品牌键缺失新键时读入并回写，旧键保留不删 */
        raw = localStorage.getItem("kabao.settings.v1");
        if (raw) localStorage.setItem("butler.settings.v1", raw);
      }
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<Settings>;
        return {
          autoRefresh: parsed.autoRefresh ?? true,
          intervalSec: parsed.intervalSec ?? 60,
          theme: parsed.theme && THEME_NAMES.has(parsed.theme) ? parsed.theme : "system",
        };
      }
    } catch {
      /* 存档损坏即回默认 */
    }
    return { autoRefresh: true, intervalSec: 60, theme: "system" };
  }

  function updateSettings(patch: Partial<Settings>) {
    settings.value = { ...settings.value, ...patch };
    localStorage.setItem("butler.settings.v1", JSON.stringify(settings.value));
  }

  /* 主题：跟随系统（prefers-color-scheme 实时跟随）或指定主题；<html data-theme> 上屏 */
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

  function applyTheme() {
    const pref = settings.value.theme;
    const resolved: Exclude<ThemeName, "system"> =
      pref === "system" ? (systemDark.matches ? "dark" : "paper") : pref;
    if (resolved === "paper") {
      delete document.documentElement.dataset.theme; /* :root 即纸墨 */
    } else {
      document.documentElement.dataset.theme = resolved;
    }
  }

  applyTheme();
  systemDark.addEventListener("change", applyTheme);
  watch(() => settings.value.theme, applyTheme);
  onBeforeUnmount(() => systemDark.removeEventListener("change", applyTheme));

  return { settings, updateSettings };
}
