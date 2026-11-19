/**
 * 数据源域（conventions/4 §2.4，业务子域分包 2026-11-14）：
 * 壳的五个端点编排（loadAll）与聚合派生（todayDone / alertCount）。
 * radar / openapi 的容错已内置于 api 层（永不 throw），此处不重复 catch。
 *
 * 逐端点独立容错（2026-11-19 用户裁决）：数据各取自本机数据库，一个接口失败
 * 不能连坐其它接口——成功的照常上屏，失败的只记该域并汇总成顶部一条提示。
 * 200 + 空数组 = 正常空态（不写 loadError），与「读不到」明确区分（红线 5 不静默）。
 */
import { computed, ref } from "vue";
import * as api from "@/shared/api";
import type { AccountItem, PlatformCandidate, PlatformItem, RadarRow, RunItem } from "@/shared/types";
import { isToday } from "@/shared/utils/format";

type DomainIssue = { label: string; reason: string };
type Settled<T> = { value: T | null; issue: DomainIssue | null };

/** 网络层失败的原句；describeIssues 用它判断「全都连不上」 */
const REASON_NETWORK = "请求没连上（服务或代理不可达）";

function describeReason(error: unknown): string {
  if (error instanceof api.ApiError) {
    return `HTTP ${error.status}${error.detail ? `：${error.detail}` : ""}`;
  }
  return REASON_NETWORK;
}

async function settle<T>(label: string, run: () => Promise<T>): Promise<Settled<T>> {
  try {
    return { value: await run(), issue: null };
  } catch (error) {
    return { value: null, issue: { label, reason: describeReason(error) } };
  }
}

function describeIssues(list: DomainIssue[], primaryAllFailed: boolean): string {
  if (!list.length) return "";
  /* 四个主端点全失败 = 服务整体不可用（dev 代理在后端停机时回 500 而非网络错误，
     所以不能只认网络层文案）；此时不该说「部分」，也不该逐个报 HTTP 码 */
  if (primaryAllFailed) return "够不到本机服务（server 未启动？）——启动后到侧栏点刷新。";
  return (
    `部分数据没读到（${list.map((i) => i.label).join("、")}）：${list[0].reason}` +
    "——其余数据照常显示，点刷新重试。"
  );
}

export function useShellData() {
  const accounts = ref<AccountItem[]>([]);
  const platforms = ref<PlatformItem[]>([]);
  /* 未导入平台（2026-11-19）：同步只纳客户端，网页版留在清单里人工导入 */
  const unimported = ref<PlatformCandidate[]>([]);
  const runs = ref<RunItem[]>([]);
  const pending = ref<RunItem[]>([]);
  const loading = ref(false);
  const loadError = ref("");
  const issues = ref<DomainIssue[]>([]);
  const loadedAt = ref("");
  const serverInfo = ref<{ title: string; version: string } | null>(null);
  /* 流量数据上收壳（账户矩阵额度列与流量页共用；radar 拉取失败静默为 []，不阻塞主数据） */
  const radarRows = ref<RadarRow[]>([]);
  const usageLoadedAt = ref("");

  async function loadAll() {
    loading.value = true;
    const [acc, run, pend, appList, radar, waiting] = await Promise.all([
      settle("账户", api.getAccounts),
      settle("台账", api.getRuns),
      settle("待处理", api.getPending),
      settle("平台", api.getPlatforms),
      settle("用量", api.getRadar),
      settle("未导入平台", api.getUnimportedPlatforms),
    ]);
    /* 成功的域才覆盖：失败的保留上次值（首次失败即空数组），不因一个域抖掉整屏 */
    if (acc.value) accounts.value = acc.value;
    if (run.value) runs.value = run.value;
    if (pend.value) pending.value = pend.value;
    if (appList.value) platforms.value = appList.value;
    if (radar.value) radarRows.value = radar.value;
    if (waiting.value) unimported.value = waiting.value;
    issues.value = [
      acc.issue,
      run.issue,
      pend.issue,
      appList.issue,
      radar.issue,
      waiting.issue,
    ].filter((issue): issue is DomainIssue => issue !== null);
    const primaryAllFailed = [acc.issue, run.issue, pend.issue, appList.issue].every(
      (issue) => issue !== null,
    );
    loadError.value = describeIssues(issues.value, primaryAllFailed);
    if (acc.value || run.value || pend.value || appList.value) {
      loadedAt.value = new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date());
      usageLoadedAt.value = loadedAt.value;
    }
    loading.value = false;
    void fetchServerInfo();
  }

  /* 版本信息纯展示，任何失败都静默（容错在 api.getOpenApiInfo）；失败保留上次值 */
  async function fetchServerInfo() {
    const info = await api.getOpenApiInfo();
    if (info) serverInfo.value = info;
  }

  /* 今日自动巡检一句话（待办栏/仪表盘速览用）：体检类 runs 按本地自然日聚合 */
  const todayDone = computed(() => {
    const today = runs.value.filter((r) => r.kind === "health.check" && isToday(r.started_at));
    if (!today.length) return null;
    return {
      label: "自动巡检",
      ok: today.filter((r) => r.signal === "ok").length,
      total: today.length,
    };
  });

  /* 提醒角标 = 待处理 + 非正常账户 + 即将到期凭据（条目数，不去重） */
  const alertCount = computed(
    () =>
      pending.value.length +
      accounts.value.filter((a) => a.signal !== "ok").length +
      accounts.value.reduce(
        (n, a) => n + a.credentials.filter((c) => c.signal === "notice").length,
        0,
      ),
  );

  return {
    accounts,
    platforms,
    unimported,
    runs,
    pending,
    radarRows,
    loading,
    loadError,
    loadedAt,
    usageLoadedAt,
    serverInfo,
    todayDone,
    alertCount,
    loadAll,
  };
}
