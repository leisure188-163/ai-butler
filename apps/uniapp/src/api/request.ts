// 统一请求层：超时/错误码/鉴权头集中在此，页面禁止手写 URL
export const API_BASE = "http://127.0.0.1:8000/api/v1"; // 上线前替换为备案域名

export async function api<T>(path: string, options: UniApp.RequestOptions = {}): Promise<T> {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${API_BASE}${path}`,
      timeout: 10000,
      ...options,
      success: (res) => (res.statusCode < 400 ? resolve(res.data as T) : reject(res)),
      fail: reject,
    });
  });
}
