// Electron 桌面壳：在线模式（WEB_URL）直接加载；离线模式拉起 Python sidecar
const { app, BrowserWindow, shell } = require("electron");
const { spawn } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");

let win = null;
let sidecar = null;

/**
 * 外链一律交给系统默认浏览器（`target="_blank"` 与壳内整页跳转都走这里）。
 * 只放行 http(s)：其他 scheme（file://、自定义协议）不猜、不外抛，显式记一条错误。
 * 返回是否已交出（调用方据此决定拦不拦）。
 */
function openInDefaultBrowser(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    console.error("无法解析的链接，已拦截：", url);
    return false;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    console.error("非 http(s) 链接，已拦截：", url);
    return false;
  }
  shell.openExternal(url).catch((err) => {
    console.error("交给系统默认浏览器失败：", url, err);
  });
  return true;
}

async function waitForHealth(port, timeoutMs = 15000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const ping = () => {
      const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() - started > timeoutMs) {
          reject(new Error("sidecar 启动超时"));
          return;
        }
        setTimeout(ping, 200);
      });
    };
    ping();
  });
}

async function resolveBaseUrl() {
  if (process.env.WEB_URL) return process.env.WEB_URL; // 在线/开发模式
  // 离线模式：启动 PyInstaller 打包的 sidecar，监听 stdout 里的 SIDECAR_PORT
  const exe =
    process.env.SIDECAR_EXE ||
    path.join(process.resourcesPath, "sidecar", "server-sidecar.exe");
  sidecar = spawn(exe, [], { windowsHide: true });
  sidecar.stdout.on("data", (chunk) => {
    const m = String(chunk).match(/SIDECAR_PORT=(\d+)/);
    if (m) sidecar.port = m[1];
  });
  const deadline = Date.now() + 15000;
  while (!sidecar.port) {
    if (Date.now() > deadline || sidecar.exitCode !== null) {
      throw new Error("sidecar 启动失败（SIDECAR_EXE 路径或打包有误）");
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  await waitForHealth(sidecar.port);
  return `http://127.0.0.1:${sidecar.port}`;
}

app.whenReady().then(async () => {
  try {
    const base = await resolveBaseUrl();
    win = new BrowserWindow({
      width: 1100,
      height: 760,
      webPreferences: { contextIsolation: true, nodeIntegration: false },
    });
    // 点击链接不该在壳内开新窗口/把应用页顶掉：新窗口一律拒绝并转系统默认浏览器
    win.webContents.setWindowOpenHandler(({ url }) => {
      openInDefaultBrowser(url);
      return { action: "deny" };
    });
    // 整页跳转同理：同源页面（hash 路由、/docs）留在壳内，跨源一律交系统浏览器
    const appOrigin = new URL(base).origin;
    win.webContents.on("will-navigate", (event, url) => {
      let target;
      try {
        target = new URL(url);
      } catch {
        event.preventDefault();
        return;
      }
      if (target.origin === appOrigin) return;
      event.preventDefault();
      openInDefaultBrowser(url);
    });
    await win.loadURL(base);
  } catch (err) {
    const { dialog } = require("electron");
    dialog.showErrorBox("启动失败", String(err));
    app.quit();
  }
});

app.on("before-quit", () => {
  if (sidecar) sidecar.kill();
});
app.on("window-all-closed", () => app.quit());
