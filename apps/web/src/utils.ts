import type { AccountItem, Signal } from "./types";

const timeFmt = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export function fmtTime(iso: string | null): string {
  return iso ? timeFmt.format(new Date(iso)) : "—";
}

/** signal 五分类 → 墨印短语（UI 谓词只消费分类，不认识 Status 字面量；quiet 尚无结论，以「—」如实留白） */
export function signalSeal(signal: Signal): string {
  if (signal === "ok") return "正常";
  if (signal === "notice") return "注意";
  if (signal === "attention") return "留意";
  if (signal === "danger") return "异常";
  return "—";
}

export function faceOf(id: string): number {
  let h = 0;
  for (const ch of id) h = (h * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
  return (h % 6) + 1;
}

export function earliestExpiry(account: AccountItem): string | null {
  const xs = account.credentials
    .map((c) => c.expires_at)
    .filter((x): x is string => Boolean(x))
    .sort();
  return xs[0] ?? null;
}
