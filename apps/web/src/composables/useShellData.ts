/**
 * 数据源域（conventions/4 §2.4，业务子域分包 2026-11-14）：
 * 壳的五个端点编排（loadAll）与聚合派生（todayDone / alertCount）。
 * radar / openapi 的容错已内置于 api 层（永不 throw），此处不重复 catch；
 * 四个主端点任一失败 → loadError（文案逐字保留）。
 */
import { computed, ref } from "vue";
import * as api from "../api";
import type { AccountItem, AppItem, RadarRow, RunItem } from "../types";
import { isToday } from "../utils";

export function useShellData() {
  const accounts = ref<AccountItem[]>([]);
  const apps = ref<AppItem[]>([]);
  const runs = ref<RunItem[]>([]);
  const pending = ref<RunItem[]>([]);
  const loading = ref(false);
  const loadError = ref("");
  const loadedAt = ref("");
  const serverInfo = ref<{ title: string; version: string } | null>(null);
  /* 流量数据上收壳（账户矩阵额度列与流量页共用；radar 拉取失败静默为 []，不阻塞主数据） */
  const radarRows = ref<RadarRow[]>([]);
  const usageLoadedAt = ref("");

  async function loadAll() {
    loading.value = true;
    loadError.value = "";
    try {
      const [acc, run, pend, appList, radar] = await Promise.all([
        api.getAccounts(),
        api.getRuns(),
        api.getPending(),
        api.getApps(),
        api.getRadar(),
      ]);
      accounts.value = acc;
      runs.value = run;
      pending.value = pend;
      apps.value = appList;
      radarRows.value = radar;
      loadedAt.value = new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date());
      usageLoadedAt.value = loadedAt.value;
    } catch {
      loadError.value = "够不到本机服务（server 未启动？）——启动后到侧栏点刷新。";
    } finally {
      loading.value = false;
    }
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
    apps,
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
