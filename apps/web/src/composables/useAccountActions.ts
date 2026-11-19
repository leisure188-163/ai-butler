/**
 * 账户域动作（conventions/4 §2.4，业务子域分包 2026-11-14）：
 * 接入（本机接入扫描）/ 领取（手动）/ 体检（R3 网页通道）/ 一键批量 / 勾选批量。
 *
 * 纪律：busyTarget/actionMsg 归本域（collectUsage 用 collecting，无跨域共享）；
 * 文案转述逐字保留（矩阵改版定稿文案）；CLAIMED/ALREADY 判定为既有先例，原样保留；
 * refresh 由壳注入（动作完成后重拉全量）；ApiError 只管非 2xx，
 * 网络异常原样传播（现状行为，不加兜底——红线 5）。
 */
import { ref } from "vue";
import * as api from "../api";
import type { CustomPlatformDraft, CustomPlatformRow } from "../types";

export function useAccountActions({ refresh }: { refresh: () => Promise<void> }) {
  const busyTarget = ref<string | null>(null);
  const actionMsg = ref<{ text: string; tone: "ok" | "warn" } | null>(null);
  /** 自定义平台目录（2026-11-18）：名册里据此标「自定义」，删除入口也只对这些开放 */
  const customPlatforms = ref<CustomPlatformRow[]>([]);

  async function loadCustomPlatforms() {
    customPlatforms.value = await api.getCustomPlatforms();
  }

  /* 平台动作：接入（本机接入扫描）/ 领取（手动领取）。结果如实展示，不造结论。 */
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

  async function claimApp(target: string) {
    busyTarget.value = target;
    actionMsg.value = null;
    try {
      const body = await api.createRun({ target });
      actionMsg.value = {
        text:
          body.status === "CLAIMED" || body.status === "ALREADY"
            ? `本轮领取完成（${body.status}）`
            : `领取未完成：${body.status ?? "未终态"}` +
              (body.repair_reason ? ` —— ${body.repair_reason}` : ""),
        tone: body.status === "CLAIMED" || body.status === "ALREADY" ? "ok" : "warn",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `领取失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
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

  /** 删除账户（2026-11-19）：账户行 + 关联凭据一并删除，不留脏数据。 */
  async function removeAccount(accountId: string) {
    busyTarget.value = accountId;
    actionMsg.value = null;
    try {
      const body = await api.deleteAccount(accountId);
      actionMsg.value = { text: body.message, tone: "ok" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `删除失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 体检探针（R3 网页通道）：kind=health.check 走同一 /runs 通道，结论如实转述 */
  async function healthApp(target: string) {
    busyTarget.value = target;
    actionMsg.value = null;
    try {
      const body = await api.createRun({ target, kind: "health.check" });
      const ok = body.status === "ALREADY";
      actionMsg.value = {
        text: ok
          ? "体检通过：会话有效"
          : `体检结论：${body.status ?? "未终态"}` +
            (body.repair_reason ? ` —— ${body.repair_reason}` : ""),
        tone: ok ? "ok" : "warn",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `体检失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 修复重试（ADR-015/016）：失效时 butler 已撤销本地副本，用户重新登录后
   * 必须先重新停靠读取客户端新凭据，再发起重试；否则会撞上已撤销的空引用。 */
  async function repairAccount(target: string, accountId: string) {
    busyTarget.value = accountId;
    actionMsg.value = null;
    try {
      const imported = await api.importPlatform(target);
      if (!(imported.accounts ?? []).includes(accountId)) {
        actionMsg.value = {
          text:
            `重新导入未发现 ${accountId}` +
            (imported.issues?.length ? ` —— ${imported.issues.join("；")}` : "") +
            "。请先在客户端完成登录，再点重试。",
          tone: "warn",
        };
        return;
      }
      const body = await api.createRun({ target, account_id: accountId });
      const ok = body.status === "CLAIMED" || body.status === "ALREADY";
      actionMsg.value = {
        text: ok
          ? `重试成功（${body.status}）`
          : `重试未通过：${body.status ?? "未终态"}` +
            (body.repair_reason ? ` —— ${body.repair_reason}` : ""),
        tone: ok ? "ok" : "warn",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `重试失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 一键批量（R2 补）：接入全部未接入 / 领取全部已接入——筛选语义在 server，端只发起与转述 */
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

  async function claimAllApps() {
    busyTarget.value = "batch";
    actionMsg.value = { text: "正在逐个领取…", tone: "ok" };
    try {
      const rows = await api.claimAllRuns();
      const done = rows.filter((r) => r.signal === "ok").length;
      const rest = rows
        .filter((r) => r.signal !== "ok")
        .map(
          (r) =>
            `${r.target}：${r.status ?? "未终态"}${r.repair_reason ? `（${r.repair_reason}）` : ""}`,
        );
      const text = rows.length
        ? `共发起 ${rows.length} 个账户，完成 ${done} 个` + (rest.length ? ` · ${rest.join(" · ")}` : "")
        : "还没有已导入的平台——先到「平台管理」页导入。";
      actionMsg.value = { text, tone: rest.length ? "warn" : "ok" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = {
          text: e.detail ?? `一键领取失败（HTTP ${e.status}）`,
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

  /* 勾选批量领取（账户矩阵）：逐个顺序执行（与 claim 单发同语义），结果如实逐条转述 */
  async function claimMany(targets: string[]) {
    if (!targets.length) return;
    busyTarget.value = "batch";
    actionMsg.value = null;
    const lines: string[] = [];
    const statuses: (string | null)[] = [];
    try {
      for (const target of targets) {
        try {
          const body = await api.createRun({ target });
          statuses.push(body.status ?? null);
          lines.push(
            `${target}：${body.status ?? "未终态"}` +
              (body.repair_reason ? `（${body.repair_reason}）` : ""),
          );
        } catch (e) {
          /* 现状两分支：非 2xx 带 detail，网络失败记「请求失败」 */
          if (e instanceof api.ApiError) {
            lines.push(`${target}：${e.detail ?? `HTTP ${e.status}`}`);
          } else {
            lines.push(`${target}：请求失败`);
          }
          statuses.push(null);
        }
      }
      const done = statuses.every((s) => s === "CLAIMED" || s === "ALREADY");
      actionMsg.value = { text: lines.join(" · "), tone: done ? "ok" : "warn" };
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 会话扫描（R5-S1）：只读枚举 + 幂等入库，结果如实转述（unbound 不是错误） */
  async function scanSessions(accountId: string) {
    busyTarget.value = accountId;
    actionMsg.value = null;
    try {
      const body = await api.scanAccountSessions(accountId);
      const unbound = body.unbound_locations.length;
      actionMsg.value = {
        text:
          `扫描完成：入库 ${body.added} 条` +
          (body.added ? `（${body.account_id} 现有 ${body.sessions.length} 处会话）` : "") +
          (unbound ? ` · ${unbound} 处未能绑定账户（如实跳过）` : ""),
        tone: "ok",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `扫描失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 改账户别名（ADR-030）：只动显示名，不动账户 id / 平台归属；空串 = 清除 */
  async function renameAccount(accountId: string, alias: string) {
    busyTarget.value = accountId;
    actionMsg.value = null;
    try {
      const updated = await api.setAccountAlias(accountId, alias);
      actionMsg.value = {
        text: updated.alias
          ? `别名已改为「${updated.alias}」`
          : "别名已清除，显示回连接器给的名称",
        tone: "ok",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `保存别名失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  return {
    busyTarget,
    actionMsg,
    customPlatforms,
    loadCustomPlatforms,
    createCustomPlatform,
    removeCustomPlatform,
    removePlatform,
    removeAccount,
    importPlatform,
    savePlatform,
    claimApp,
    healthApp,
    repairAccount,
    importAllPlatforms,
    resyncPlatforms,
    adoptPlatform,
    claimAllApps,
    claimMany,
    scanSessions,
    renameAccount,
  };
}
