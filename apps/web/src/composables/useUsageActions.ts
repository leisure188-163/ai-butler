/**
 * 流量域动作（conventions/4 §2.4，业务子域分包 2026-11-14）：
 * 立即采集 + 结果如实分列转述（采集汇总逻辑上收壳）。
 * collecting/usageMsg 归本域；radarRows 经参数注入（radar 名称回退用）。
 */
import { ref, type Ref } from "vue";
import * as api from "../api";
import type { CollectOutcome, RadarRow } from "../types";

export function useUsageActions({
  refresh,
  radarRows,
}: {
  refresh: () => Promise<void>;
  radarRows: Ref<RadarRow[]>;
}) {
  const collecting = ref(false);
  const usageMsg = ref<{ text: string; tone: "ok" | "warn" } | null>(null);

  /* 用量采集（流量页「立即采集」）：结果如实分列，不造总结论 */
  async function collectUsage() {
    collecting.value = true;
    usageMsg.value = null;
    try {
      const outcomes = await api.collectUsage();
      if (!Array.isArray(outcomes)) {
        usageMsg.value = { text: "采集响应形状异常（预期结果列表）", tone: "warn" };
        return;
      }
      usageMsg.value = {
        text: summarizeCollect(outcomes),
        tone: outcomes.some((o) => o.error) ? "warn" : "ok",
      };
    } catch (e) {
      if (e instanceof api.ApiError) {
        usageMsg.value = { text: e.detail ?? `采集失败（HTTP ${e.status}）`, tone: "warn" };
      } else {
        usageMsg.value = { text: "采集失败——够不到本机服务。", tone: "warn" };
      }
    } finally {
      collecting.value = false;
      await refresh();
    }
  }

  function summarizeCollect(outcomes: CollectOutcome[]): string {
    if (!outcomes.length) return "没有可采集的账户——先到「平台」页导入。";
    return outcomes
      .map((o) => {
        const name =
          radarRows.value.find((r) => r.account_id === o.account_id)?.account_name ?? o.account_id;
        if (o.error) return `${name}：${o.error}`;
        const saved = [
          o.snapshot_saved ? "余额" : "",
          o.aggregate_saved ? "汇总" : "",
          o.ledger_saved > 0 ? `流水×${o.ledger_saved}` : "",
        ]
          .filter(Boolean)
          .join("·");
        const low = o.quota_low.length ? `；低额：${o.quota_low.join("、")}` : "";
        return `${name}：${saved || "无新数据"}${low}`;
      })
      .join("；");
  }

  return { collecting, usageMsg, collectUsage };
}
