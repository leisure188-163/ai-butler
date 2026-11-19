/**
 * 账户域动作（conventions/4 §2.4，业务子域分包 2026-11-20 进一步按域拆分）：
 * 删除账户 / 改别名 / 修复重试 / 会话扫描。平台动作见 domains/platforms/usePlatformActions，
 * 领取动作见 domains/runs/useRunActions。
 *
 * 纪律：busyTarget/actionMsg 由壳注入（跨域单实例，见 shared/composables/useActionState）；
 * 文案转述逐字保留（矩阵改版定稿文案）；refresh 由壳注入；
 * ApiError 只管非 2xx，网络异常原样传播（不加兜底——红线 5）。
 */
import * as api from "@/shared/api";
import type { ActionState } from "@/shared/composables/useActionState";

export function useAccountActions({
  refresh,
  state,
}: {
  refresh: () => Promise<void>;
  state: ActionState;
}) {
  const { busyTarget, actionMsg } = state;

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

  return { removeAccount, repairAccount, scanSessions, renameAccount };
}
