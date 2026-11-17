/**
 * 账户域动作（conventions/4 §2.4，业务子域分包 2026-11-14）：
 * 导入（本机接入扫描）/ 领取（手动）/ 体检（R3 网页通道）/ 一键批量 / 勾选批量。
 *
 * 纪律：busyTarget/actionMsg 归本域（collectUsage 用 collecting，无跨域共享）；
 * 文案转述逐字保留（矩阵改版定稿文案）；CLAIMED/ALREADY 判定为既有先例，原样保留；
 * refresh 由壳注入（动作完成后重拉全量）；ApiError 只管非 2xx，
 * 网络异常原样传播（现状行为，不加兜底——红线 5）。
 */
import { ref } from "vue";
import * as api from "../api";

export function useAccountActions({ refresh }: { refresh: () => Promise<void> }) {
  const busyTarget = ref<string | null>(null);
  const actionMsg = ref<{ text: string; tone: "ok" | "warn" } | null>(null);

  /* 应用动作：导入（本机接入扫描）/ 领取（手动领取）。结果如实展示，不造结论。 */
  async function importApp(target: string) {
    busyTarget.value = target;
    actionMsg.value = null;
    try {
      const body = await api.importApp(target);
      const issues = body.issues ?? [];
      const imported = body.accounts ?? [];
      actionMsg.value = {
        text: imported.length
          ? `已导入：${imported.join("、")}` + (issues.length ? ` · ${issues.join("；")}` : "")
          : issues.length
            ? issues.join("；")
            : "没有发现可导入的应用。",
        tone: imported.length ? "ok" : "warn",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `导入失败（HTTP ${e.status}）`, tone: "warn" };
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
      const imported = await api.importApp(target);
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

  /* 一键批量（R2 补）：导入全部未接入 / 领取全部已接入——筛选语义在 server，端只发起与转述 */
  async function importAllApps() {
    busyTarget.value = "batch";
    actionMsg.value = { text: "正在扫描本机客户端…", tone: "ok" };
    try {
      const results = await api.importAllApps();
      const imported = results.flatMap((r) => r.accounts);
      const issues = results.flatMap((r) => r.issues.map((i) => `${r.target}：${i}`));
      const empty = results
        .filter((r) => !r.accounts.length && !r.issues.length)
        .map((r) => r.target);
      const text =
        [
          imported.length ? `已导入：${imported.join("、")}` : "",
          empty.length ? `未发现登录态：${empty.join("、")}` : "",
          ...issues,
        ]
          .filter(Boolean)
          .join(" · ") || "没有待导入的应用。";
      actionMsg.value = { text, tone: issues.length ? "warn" : "ok" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = {
          text: e.detail ?? `一键导入失败（HTTP ${e.status}）`,
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

  /* 同步全部（2026-11-17）：已导入应用也要重扫，捕获客户端当前登录态，
   * 新账户按稳定 key 追加；单家失败只入 issues，不阻断其余应用。 */
  async function syncAllApps(targets: string[]) {
    if (!targets.length) return;
    busyTarget.value = "batch";
    actionMsg.value = { text: "正在同步本机账户…", tone: "ok" };
    const imported: string[] = [];
    const issues: string[] = [];
    try {
      for (const target of targets) {
        try {
          const body = await api.importApp(target);
          imported.push(...(body.accounts ?? []));
          issues.push(...(body.issues ?? []).map((issue) => `${target}：${issue}`));
        } catch (e) {
          if (e instanceof api.ApiError) {
            issues.push(`${target}：${e.detail ?? `HTTP ${e.status}`}`);
          } else {
            throw e;
          }
        }
      }
      actionMsg.value = {
        text: imported.length
          ? `已同步：${imported.join("、")}` + (issues.length ? ` · ${issues.join("；")}` : "")
          : issues.length
            ? issues.join("；")
            : "当前没有可同步的账户。",
        tone: issues.length ? "warn" : "ok",
      };
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
        : "还没有已导入的应用——先到「应用」页导入。";
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

  return {
    busyTarget,
    actionMsg,
    importApp,
    syncAllApps,
    claimApp,
    healthApp,
    repairAccount,
    importAllApps,
    claimAllApps,
    claimMany,
    scanSessions,
  };
}
