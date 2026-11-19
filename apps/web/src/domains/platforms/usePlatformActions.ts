/**
 * 平台域动作（2026-11-20 按业务域分包）：接入 / 扫描本机 / 人工导入 / 编辑 / 移出名册 /
 * 自定义平台增删。账户动作见 domains/accounts/useAccountActions，领取动作见
 * domains/runs/useRunActions。
 *
 * 纪律：busyTarget/actionMsg 由壳注入（跨域单实例）；文案逐字保留；refresh 由壳注入；
 * ApiError 只管非 2xx，网络异常原样传播（红线 5）。
 */
import { ref } from "vue";
import * as api from "@/shared/api";
import type { ActionState } from "@/shared/composables/useActionState";
import type { CustomPlatformDraft, CustomPlatformRow } from "@/shared/types";

export function usePlatformActions({
  refresh,
  state,
}: {
  refresh: () => Promise<void>;
  state: ActionState;
}) {
  const { busyTarget, actionMsg } = state;
  /** 自定义平台目录（2026-11-18）：名册里据此标「自定义」，删除入口也只对这些开放 */
  const customPlatforms = ref<CustomPlatformRow[]>([]);

  async function loadCustomPlatforms() {
    customPlatforms.value = await api.getCustomPlatforms();
  }

  /* 接入（本机接入扫描）：结果如实展示，不造结论。 */
  async function importPlatform(target: string) {
    busyTarget.value = target;
    actionMsg.value = null;
    try {
      const body = await api.importPlatform(target);
      const issues = body.issues ?? [];
      const imported = body.accounts ?? [];
      actionMsg.value = {
        text: imported.length
          ? `已接入：${imported.join("、")}` + (issues.length ? ` · ${issues.join("；")}` : "")
          : issues.length
            ? issues.join("；")
            : "没有发现可接入的平台。",
        tone: imported.length ? "ok" : "warn",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `接入失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e; /* 网络异常原样传播（现状行为） */
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 自定义平台（2026-11-18）：新建 → server 校验落盘 + 热加载；失败逐字转述 422 detail。
     注意这里不造结论：热加载是否真的进了名册，靠 refresh() 后的名册行说话。 */
  async function createCustomPlatform(draft: CustomPlatformDraft) {
    busyTarget.value = draft.code;
    actionMsg.value = null;
    try {
      const body = await api.saveCustomPlatform(draft);
      actionMsg.value = { text: body.message, tone: "ok" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `保存失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await loadCustomPlatforms();
      await refresh();
    }
  }

  async function removeCustomPlatform(code: string) {
    busyTarget.value = code;
    actionMsg.value = null;
    try {
      const body = await api.deleteCustomPlatform(code);
      actionMsg.value = { text: body.message, tone: body.deleted ? "ok" : "warn" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `删除失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await loadCustomPlatforms();
      await refresh();
    }
  }

  /** 移出名册（2026-11-19）：平台事实行删除，账户/台账保留；可回「未导入」重新导入。 */
  async function removePlatform(code: string) {
    busyTarget.value = code;
    actionMsg.value = null;
    try {
      const body = await api.removePlatform(code);
      actionMsg.value = { text: body.message, tone: body.removed ? "ok" : "warn" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `移出失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 一键接入（R2 补）：筛选语义在 server，端只发起与转述 */
  async function importAllPlatforms() {
    busyTarget.value = "batch";
    actionMsg.value = { text: "正在扫描本机客户端…", tone: "ok" };
    try {
      const results = await api.importAllPlatforms();
      const imported = results.flatMap((r) => r.accounts);
      const issues = results.flatMap((r) => r.issues.map((i) => `${r.target}：${i}`));
      const empty = results
        .filter((r) => !r.accounts.length && !r.issues.length)
        .map((r) => r.target);
      const text =
        [
          imported.length ? `已接入：${imported.join("、")}` : "",
          empty.length ? `未发现登录态：${empty.join("、")}` : "",
          ...issues,
        ]
          .filter(Boolean)
          .join(" · ") || "没有待接入的平台。";
      actionMsg.value = { text, tone: issues.length ? "warn" : "ok" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = {
          text: e.detail ?? `接入失败（HTTP ${e.status}）`,
          tone: "warn",
        };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 扫描本机（2026-11-19 用户裁决，2026-11-20 修复）：一次点击完成两件事——刷新平台名册 +
     全量重扫本机客户端账户。只扫客户端；网页版仍留在「未导入的平台」里由用户手动导入。
     典型场景：名册被清空、连接器升级、账户被删后需要重新接入客户端。

     2026-11-20 修复：原来调 import-all 默认只接「零账户」的平台，于是名册里平台都已有
     账户时 results 为空 → 提示「本机客户端账户均已接入」，而实际上一个平台都没扫，
     多账号客户端（豆包双账号）漏接的账号也永远补不上。改为 include_docked=true 全量
     重扫（dock/注册均按 (platform, account_code) 幂等，只补新增、不动既有），
     文案只报事实：名册数、扫到账户数、未发现登录态、异常。 */
  async function resyncPlatforms() {
    busyTarget.value = "resync";
    actionMsg.value = { text: "正在扫描本机客户端…", tone: "ok" };
    try {
      const rows = await api.resyncPlatforms();
      const results = await api.importAllPlatforms(true);
      const imported = results.flatMap((r) => r.accounts);
      const issues = results.flatMap((r) => r.issues.map((i) => `${r.target}：${i}`));
      const empty = results
        .filter((r) => !r.accounts.length && !r.issues.length)
        .map((r) => r.target);
      const text =
        [
          `平台名册：${rows.length} 个`,
          imported.length ? `已扫到 ${imported.length} 个账户` : "",
          empty.length ? `未发现登录态：${empty.join("、")}` : "",
          ...(results.length === 0 ? ["名册里没有可扫描的本机客户端"] : []),
          ...issues,
        ]
          .filter(Boolean)
          .join(" · ") || "没有可扫描的本机客户端。";
      actionMsg.value = { text, tone: issues.length ? "warn" : "ok" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = {
          text: e.detail ?? `同步失败（HTTP ${e.status}）`,
          tone: "warn",
        };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 人工导入平台（2026-11-19）：自动同步只纳本机客户端，网页版在这里按需导入。
     纳册 + 立即接入一步完成；已导入的平台重复点等同「重新接入」。 */
  async function adoptPlatform(target: string) {
    busyTarget.value = target;
    actionMsg.value = { text: `正在导入 ${target}…`, tone: "ok" };
    try {
      const res = await api.adoptPlatform(target);
      const text =
        [
          res.accounts?.length ? `已导入并接入：${res.accounts.join("、")}` : "已导入平台（未发现登录态）",
          ...(res.issues ?? []),
        ]
          .filter(Boolean)
          .join(" · ");
      actionMsg.value = { text, tone: (res.issues ?? []).length ? "warn" : "ok" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = {
          text: e.detail ?? `导入失败（HTTP ${e.status}）`,
          tone: "warn",
        };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 编辑平台（2026-11-18）：显示名 / 启停 / 调度三合一；失败按 ApiError 转提示 */
  async function savePlatform(
    target: string,
    patch: { platform_name?: string | null; active?: boolean; times?: string[] | null },
  ) {
    busyTarget.value = target;
    try {
      const updated = await api.patchPlatform(target, patch);
      const bits: string[] = [];
      if (patch.platform_name !== undefined) bits.push(`名称「${updated.platform_name}」`);
      if (patch.active !== undefined) bits.push(patch.active ? "已启用" : "已停用（不再定时领取）");
      if (patch.times === null) {
        bits.push("已恢复平台默认调度");
      } else if (patch.times !== undefined) {
        bits.push(
          updated.schedule_times.length
            ? `调度 ${updated.schedule_times.join("、")}`
            : "调度已清空（不排班）",
        );
      }
      actionMsg.value = {
        text: bits.length ? `已保存：${bits.join(" · ")}` : "没有改动",
        tone: "ok",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = {
          text: e.detail ?? `改调度失败（HTTP ${e.status}）`,
          tone: "warn",
        };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  return {
    customPlatforms,
    loadCustomPlatforms,
    importPlatform,
    importAllPlatforms,
    resyncPlatforms,
    adoptPlatform,
    savePlatform,
    removePlatform,
    createCustomPlatform,
    removeCustomPlatform,
  };
}
