/**
 * 运行域动作（2026-11-20 按业务域分包）：手动领取 / 一键领取 / 勾选批量 / 体检探针。
 *
 * 三个动作都走 /runs 通道；结论如实转述（CLAIMED/ALREADY 判定为既有先例，原样保留）。
 * busyTarget/actionMsg 由壳注入（跨域单实例）；refresh 由壳注入；网络异常原样传播（红线 5）。
 */
import * as api from "@/shared/api";
import type { ActionState } from "@/shared/composables/useActionState";

export function useRunActions({
  refresh,
  state,
}: {
  refresh: () => Promise<void>;
  state: ActionState;
}) {
  const { busyTarget, actionMsg } = state;

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

  return { claimApp, healthApp, claimAllApps, claimMany };
}
