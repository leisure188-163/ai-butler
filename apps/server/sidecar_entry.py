# Electron 离线模式的 sidecar 入口：API + web 静态资源同源伺服
# 打包: pyinstaller --onefile --name server-sidecar \
#   --add-data "../web/dist:web_dist" sidecar_entry.py
import os
import socket
import sys
import threading
import time

import uvicorn
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from server.main import create_app  # noqa: E402


def resolve_web_dist() -> str | None:
    candidates = [
        os.path.join(os.path.dirname(sys.executable), "web_dist"),  # PyInstaller onefile
        os.path.join(os.path.dirname(__file__), "web_dist"),  # 源码运行
    ]
    return next((p for p in candidates if os.path.isdir(p)), None)


def pick_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> None:
    app = create_app()
    web_dist = resolve_web_dist()
    if web_dist:
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    port = int(os.environ.get("SIDECAR_PORT", "0")) or pick_free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()

    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        print("SIDECAR_ERROR=failed to start", flush=True)
        sys.exit(1)
    print(f"SIDECAR_PORT={port}", flush=True)

    try:  # 保持进程存活，Ctrl+C 优雅退出
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.should_exit = True


if __name__ == "__main__":
    main()
