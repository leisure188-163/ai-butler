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
import type { AccountCreatePayload, AccountPatch } from "@/domains/accounts/api";

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

  /* 手建账户（ADR-033）：编码由 server 生成并冻结；错误 detail 直显 */
  async function createAccount(payload: AccountCreatePayload) {
    busyTarget.value = "__create__";
    actionMsg.value = null;
    try {
      const created = await api.createAccount(payload);
      actionMsg.value = {
        text: `已创建账户「${created.account_label}」（${created.account_id}）`,
        tone: "ok",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `创建失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 账户编辑（ADR-033）：别名/显示名/启停/账户级地址/真实身份，永不改编址 */
  async function updateAccount(accountId: string, patch: AccountPatch) {
    busyTarget.value = accountId;
    actionMsg.value = null;
    try {
      const updated = await api.patchAccount(accountId, patch);
      const messages: string[] = [];
      if ("alias" in patch) {
        messages.push(updated.alias ? `别名已改为「${updated.alias}」` : "别名已清除");
      }
      if ("account_name" in patch) messages.push("显示名已更新");
      if ("active" in patch) messages.push(updated.active ? "账户已启用" : "账户已停用");
      if ("base_url" in patch) messages.push("接入地址已更新");
      if ("identity" in patch) messages.push("身份信息已更新");
      actionMsg.value = { text: messages.join("；") || "账户已更新", tone: "ok" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `更新失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 追加密钥槽位（ADR-033）：明文只上行一次，页面不回显 */
  async function addCredential(
    accountId: string,
    key: { kind: string; secret: string; slot: string; label: string },
  ) {
    busyTarget.value = accountId;
    actionMsg.value = null;
    try {
      const credential = await api.addAccountCredential(accountId, key);
      actionMsg.value = {
        text: `已写入 ${credential.kind} 槽位「${credential.label || credential.slot}」`,
        tone: "ok",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `写入凭据失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  /* 撤销单槽位（ADR-033）：归档旧值、清主引用，客户端会话不受影响 */
  async function revokeCredential(accountId: string, kind: string, slot: string) {
    busyTarget.value = accountId;
    actionMsg.value = null;
    try {
      await api.revokeAccountCredential(accountId, kind, slot);
      actionMsg.value = { text: `已撤销凭据槽位 ${kind}@${slot}`, tone: "ok" };
    } catch (e) {
      if (e instanceof api.ApiError) {
        actionMsg.value = { text: e.detail ?? `撤销失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        throw e;
      }
    } finally {
      busyTarget.value = null;
      await refresh();
    }
  }

  return {
    removeAccount,
    repairAccount,
    scanSessions,
    renameAccount,
    createAccount,
    updateAccount,
    addCredential,
    revokeCredential,
  };
}
