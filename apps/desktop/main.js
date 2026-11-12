// Electron 桌面壳：在线模式（WEB_URL）直接加载；离线模式拉起 Python sidecar
const { app, BrowserWindow } = require("electron");
const { spawn } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");

let win = null;
let sidecar = null;

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
