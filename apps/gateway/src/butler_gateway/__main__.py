"""python -m butler_gateway：网关进程入口（uvicorn 单进程，G1 骨架）。

启动：``uv run python -m butler_gateway``（默认 127.0.0.1:8100，
BUTLER_GATEWAY_PORT / BUTLER_SERVER_URL 覆盖，见 butler_gateway.config）。
"""

from __future__ import annotations

import uvicorn

from butler_gateway import config


def main() -> None:
    uvicorn.run(
        "butler_gateway.app:create_app",
        factory=True,
        host=config.gateway_host(),
        port=config.gateway_port(),
        log_level="info",
    )


if __name__ == "__main__":
    main()
