"""豆包活动页的页面侧 JS 常量（从 adapter.py 拆出控制行数）。

纯字符串/常量，不含控制流：按钮查找、页面诊断、detail 页面 fetch（ADR-017）、
只读请求旁路安装与读取。
"""

from __future__ import annotations

import json

#: 签到按钮文案精确匹配（PROTOCOL §6 ①：模糊匹配会误点"签到领额度"类标题）。
_BUTTON_TEXTS = ("立即签到", "今日签到", "签到")

#: 找按钮 + 滚动扫找 + 中心坐标（语义 = PROTOCOL §6 ①②③，页面契约非代码搬运）。
_FIND_CLICK_JS = """
(() => {
  const want = %s;
  const pick = () => [...document.querySelectorAll('*')].find(el =>
      el.children.length <= 2 &&
      want.includes((el.textContent || '').trim()) &&
      getComputedStyle(el).pointerEvents !== 'none');
  let el = pick();
  if (!el) {
    const step = Math.round(window.innerHeight * 0.7);
    for (let pos = 0; pos <= document.body.scrollHeight; pos += step) {
      window.scrollTo(0, pos);
      el = pick();
      if (el) break;
    }
  }
  if (!el) return null;
  el.scrollIntoView({block: 'center'});
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
          text: (el.textContent || '').trim()};
})()
""" % json.dumps(list(_BUTTON_TEXTS))

#: 找不到按钮时的页面诊断摘要（脱敏：纯文本，且只取前段）。
_PAGE_TEXT_JS = "document.body.innerText.slice(0, 300)"

#: 只读旁路：在活动页记录客户端自己发的 campaign 请求（fetch/XHR 均覆盖）。
#: 只在 capture=True 时安装；包装器始终调用原函数，不改写请求。
#: 同一活动页复用时只重置 entries，避免把上一次（甚至另一账户）的请求混进本次样本。
_TRACE_INSTALL_JS = """
(() => {
  if (window.__butlerTrace && window.__butlerTrace.__installed) {
    window.__butlerTrace.entries.length = 0;
    window.__butlerTrace.installedAt = Date.now();
    return {reset: true};
  }
  const state = window.__butlerTrace = {__installed: true, entries: [], installedAt: Date.now()};
  const MAX = 20;
  const match = (url) => /\\/alice\\/ug\\/campaign\\/(?:landing\\/checkin|item\\/reward\\/claim|v3\\/detail)(?:\\/)?(?:\\?|$)/.test(String(url || ''));
  const record = (entry) => {
    if (entry && match(entry.url) && state.entries.length < MAX) state.entries.push(entry);
  };
  const headersToObject = (headers) => {
    const out = {};
    try {
      if (!headers) return out;
      if (typeof headers.forEach === 'function') {
        headers.forEach((value, key) => { out[String(key)] = String(value); });
        return out;
      }
      if (Array.isArray(headers)) {
        for (const pair of headers) out[String(pair[0])] = String(pair[1]);
        return out;
      }
      for (const key of Object.keys(headers)) out[key] = String(headers[key]);
    } catch (e) {}
    return out;
  };
  const origFetch = window.fetch;
  if (typeof origFetch === 'function' && !state.fetchWrapped) {
    state.fetchWrapped = true;
    window.fetch = function(input, init) {
      let request = null;
      try {
        request = (typeof Request !== 'undefined' && input instanceof Request)
          ? input : new Request(input, init);
      } catch (e) {}
      const entry = request ? {
        transport: 'fetch', method: request.method, url: request.url,
        headers: headersToObject(request.headers), body: null, response: null,
      } : null;
      if (entry) {
        record(entry);
        try {
          request.clone().text().then((text) => { entry.body = text.slice(0, 4000); }).catch(() => {});
        } catch (e) {}
      }
      const promise = origFetch.apply(this, arguments);
      if (entry) {
        try {
          const tracked = promise && typeof promise.then === 'function'
            ? promise : Promise.resolve(promise);
          tracked.then((response) => {
            try {
              response.clone().text().then((text) => {
                entry.response = {status: response.status, body: text.slice(0, 4000)};
              }).catch(() => {});
            } catch (e) {}
          }).catch(() => {});
        } catch (e) {}
      }
      return promise;
    };
  }
  const XHR = window.XMLHttpRequest;
  if (XHR && XHR.prototype && !state.xhrWrapped) {
    state.xhrWrapped = true;
    const origOpen = XHR.prototype.open;
    const origSend = XHR.prototype.send;
    const origSetHeader = XHR.prototype.setRequestHeader;
    XHR.prototype.open = function(method, url) {
      let absolute = String(url || '');
      try { absolute = new URL(absolute, location.href).href; } catch (e) {}
      this.__butlerReq = {
        transport: 'xhr', method: String(method || ''), url: absolute,
        headers: {}, body: null, response: null,
      };
      return origOpen.apply(this, arguments);
    };
    XHR.prototype.setRequestHeader = function(key, value) {
      try {
        if (this.__butlerReq) this.__butlerReq.headers[String(key)] = String(value);
      } catch (e) {}
      return origSetHeader.apply(this, arguments);
    };
    XHR.prototype.send = function(body) {
      const entry = this.__butlerReq;
      if (entry) {
        entry.body = body == null ? null : String(body).slice(0, 4000);
        try {
          this.addEventListener('load', () => {
            let text = '';
            try { text = String(this.responseText || '').slice(0, 4000); } catch (e) {}
            entry.response = {status: this.status, body: text};
          });
        } catch (e) {}
        record(entry);
      }
      return origSend.apply(this, arguments);
    };
  }
  return {installed: true};
})()
"""

_TRACE_READ_JS = """
(() => {
  const state = window.__butlerTrace;
  if (!state) return {installed: false, entries: []};
  return {installed: true, installedAt: state.installedAt, entries: state.entries || []};
})()
"""

#: detail 只读查询 = 活动页上下文 fetch（ADR-017：全链路零裸请求——Cookie/
#: Origin/Referer/UA 由浏览器原生自带，msToken/a_bogus 由客户端网络栈在页面
#: JS 可见层之下自动补签，2026-11-16 Windows + 11-17 mac 双机 spike 实证）。
#: __URL__ = detail path + 公共查询参数串、__GROUP__ = 活动分组码（adapter 注入，
#: 单源在 adapter 常量）；哨兵键 butler_http_status 回传非 2xx（保持旧裸 HTTP
#: 「非 2xx = 传输层失败」语义，业务码判定只对 2xx JSON 生效，PROTOCOL §2）。
_DETAIL_FETCH_JS = """
(async () => {
  const resp = await fetch("__URL__", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    credentials: "include",
    body: JSON.stringify({campaign_group_code: "__GROUP__"})
  });
  if (!resp.ok) return {butler_http_status: resp.status};
  return await resp.json();
})()
"""

_SETTLE_SECONDS = 3.0  # 点击后等客户端 SDK 发完请求（PROTOCOL §6 ⑤）
_DETAIL_WAIT_SECONDS = 25.0  # detail 页面 fetch 求值上限（2026-11-17 mac spike 实证量级）
_FIND_RETRIES = 3  # 活动页可能还在加载（PROTOCOL §6 ⑥）
#: 点击后复查退避序列（2026-11-16 真机取证：点击生效但状态翻转有延迟，
#: 3s 即查会误判 FAILED——退避复查 3 次再判失败，PROTOCOL §3 FAILED 行语义）。
_RECHECK_DELAYS = (3.0, 5.0, 8.0)
#: 杀净与拉起之间的落定间隔（2026-11-17 真机：旧实例未完全退出时立即拉起
#: 撞单实例锁，新实例静默消失——settle 后再拉起 + 轮询绑定一次成功）。
_KILL_SETTLE_SECONDS = 6.0

#: 失败留证：签到区相关元素快照。配合 _TOPMOST_AT_JS 判读三种失败形态——
#: ①有「立即签到」但 disabled/pointerEvents=none（按钮存在但不可点）；
#: ②只剩「每日签到+200 额度」大卡（已签态或界面改版）；③两者都没有（页面没加载好）。
_SIGNIN_AREA_JS = """
(() => {
  const items = [];
  for (const el of document.querySelectorAll('button,[role=button],a,span,div')) {
    const t = (el.textContent || '').trim();
    if (!t || t.length > 14) continue;
    if (!/(签到|已签|领取|打卡)/.test(t)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 10 || r.height < 8) continue;
    items.push({text: t, tag: el.tagName,
                cls: String(el.className || '').slice(0, 60),
                x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
                w: Math.round(r.width), h: Math.round(r.height),
                disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true',
                pe: getComputedStyle(el).pointerEvents});
  }
  return {items: items.slice(0, 20), scrollY: Math.round(window.scrollY),
          viewport: [window.innerWidth, window.innerHeight], href: String(location.href)};
})()
"""

#: 失败留证：点击坐标上真正吃到这一击的元素。%d 由 adapter 填入 x、y；
#: 返回文本与目标「立即签到」不一致 = 点到遮挡层/空白（点空），不是平台拒绝。
_TOPMOST_AT_JS = """
(() => {
  const el = document.elementFromPoint(%d, %d);
  if (!el) return null;
  return {text: (el.textContent || '').trim().slice(0, 60), tag: el.tagName,
          cls: String(el.className || '').slice(0, 60)};
})()
"""
