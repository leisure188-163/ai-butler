/**
 * 账户行派生逻辑（平台/账户关联重设计 v1）：
 * 从 MatrixTable 抽出「账户 → 平台」「今日动作」「额度」「凭据」「最近操作」
 * 的纯前端派生，供平铺矩阵与分组矩阵共用——一处规则，两个视图零漂移。
 *
 * 纪律（红线 2）：只消费 core 出产的 signal / repair_reason / repair_hint，
 * 端不写状态映射，不改写 core 文案。accountLabel 只做展示格式化（去平台前缀），
 * 不参与任何业务判定。
 */
import { computed, type ComputedRef, type Ref } from "vue";
import type { AccountItem, PlatformItem, RadarRow, RunItem } from "../types";
import { earliestExpiry, isToday } from "../utils";

export type TodayAction = {
  label: string;
  cls: "ok" | "notice" | "attention" | "danger" | "quiet";
  reason: string | null;
};

export type QuotaView = {
  text: string;
  low: boolean;
  /** 0..1，用于水位条；无数据为 null */
  ratio: number | null;
};

export function useAccountRows({
  accounts,
  platforms,
  radar,
  runs,
}: {
  accounts: Ref<readonly AccountItem[]> | ComputedRef<readonly AccountItem[]>;
  platforms: Ref<readonly PlatformItem[]> | ComputedRef<readonly PlatformItem[]>;
  radar: Ref<readonly RadarRow[]> | ComputedRef<readonly RadarRow[]>;
  runs: Ref<readonly RunItem[]> | ComputedRef<readonly RunItem[]>;
}) {
  /** 归属以账户的 platform_code 为准（AppOut.account_id 只是首账号，不能据此判 2、3 号账户） */
  function appOf(account: AccountItem): PlatformItem | null {
    return (
      platforms.value.find((x) => x.id === account.platform_code) ??
      platforms.value.find((x) => x.account_ids?.includes(account.account_id)) ??
      null
    );
  }

  /** 昵称优先、ID 为辅：别名（用户起的）> account_name（core 出产）> account_code。
   * 别名存在的意义就是盖掉连接器给的泛名（如 Trae CN），所以放在最前。 */
  function accountLabel(account: AccountItem): string {
    const alias = account.alias?.trim() || "";
    if (alias) return alias;
    const platform = appOf(account);
    const name = account.account_name?.trim() || "";
    if (!name || (platform && name === platform.display)) return account.account_code;
    if (platform && name.startsWith(`${platform.display} · `)) {
      return name.slice(platform.display.length + 3).trim();
    }
    return name;
  }

  const todayRunsByAccount = computed(() => {
    const map = new Map<string, RunItem[]>();
    for (const r of runs.value) {
      if (!isToday(r.started_at)) continue;
      const list = map.get(r.account_id) ?? [];
      list.push(r);
      map.set(r.account_id, list);
    }
    return map;
  });

  const todayAction = computed(() => {
    const result = new Map<string, TodayAction>();
    for (const a of accounts.value) {
      const runList = todayRunsByAccount.value.get(a.account_id) ?? [];
      if (!runList.length) {
        result.set(a.account_id, { label: "未做", cls: "quiet", reason: a.repair_hint });
      } else if (runList.some((r) => r.signal === "ok")) {
        result.set(a.account_id, { label: "已完成", cls: "ok", reason: null });
      } else if (runList.some((r) => r.signal !== "quiet")) {
        const bad = runList.find((r) => r.signal !== "quiet");
        result.set(a.account_id, {
          label: "未完成",
          cls: "attention",
          reason: bad?.repair_reason ?? a.repair_hint,
        });
      } else {
        result.set(a.account_id, { label: "进行中", cls: "notice", reason: a.repair_hint });
      }
    }
    return result;
  });

  function ratioOf(remaining: number, total: number): number {
    return total > 0 ? remaining / total : 1;
  }

  function quotaOf(accountId: string): QuotaView | null {
    const row = radar.value.find((r) => r.account_id === accountId);
    if (!row) return null;
    const active = row.packages.filter((p) => p.remaining > 0);
    if (!active.length) {
      return row.packages.length ? { text: "已耗尽", low: false, ratio: 0 } : null;
    }
    const tightest = active.reduce((min, p) =>
      ratioOf(p.remaining, p.total) < ratioOf(min.remaining, min.total) ? p : min,
    );
    const more = active.length > 1 ? ` +${active.length - 1}` : "";
    const ratio = Math.max(0, Math.min(1, ratioOf(tightest.remaining, tightest.total)));
    return {
      text: `${tightest.remaining}/${tightest.total} ${tightest.unit}${more}`,
      low: row.quota_low.includes(tightest.name),
      ratio,
    };
  }

  function credNoticeOf(account: AccountItem): boolean {
    return account.credentials.some((c) => c.signal === "notice");
  }

  function lastRunAtOf(accountId: string): string | null {
    return runs.value.find((r) => r.account_id === accountId)?.started_at ?? null;
  }

  return {
    appOf,
    accountLabel,
    todayAction,
    quotaOf,
    earliestExpiry,
    credNoticeOf,
    lastRunAtOf,
  };
}
