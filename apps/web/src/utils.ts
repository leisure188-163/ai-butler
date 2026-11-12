import type { AccountItem } from "./types";

const timeFmt = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export function fmtTime(iso: string | null): string {
  return iso ? timeFmt.format(new Date(iso)) : "—";
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
