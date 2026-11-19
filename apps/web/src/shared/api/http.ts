/**
 * 端点访问基础层（2026-11-20 按业务域分包）：URL 基址 + 统一 fetch 封装。
 *
 * 各业务域的端点函数在 domains/<域>/api.ts 里，本文件只保留跨域共用的
 * 传输语义（非 2xx 抛 ApiError、detail/status 透传；网络异常原样传播，红线 5）。
 */

export const apiBase = "/api/v1";

/** 非 2xx 响应：server 的 detail 惯例 + HTTP 状态码透传，文案由调用方拼装 */
export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(status: number, detail?: string) {
    super(detail ?? `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  // 代理/网关在服务不可达时常回 HTML 或空响应：先读文本再解析，避免
  // resp.json() 的 SyntaxError 冒充业务错误。非 JSON 显式抛 ApiError（红线 5 仍 throw）
  const text = await resp.text();
  let body: unknown = null;
  if (text.trim()) {
    try {
      body = JSON.parse(text);
    } catch {
      throw new ApiError(resp.status, `非 JSON 响应：${text.slice(0, 120)}`);
    }
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, (body as { detail?: string } | null)?.detail);
  }
  return (body ?? {}) as T;
}

export function post(body?: unknown): RequestInit {
  return {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export function sendJson(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
