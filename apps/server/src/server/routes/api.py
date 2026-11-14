"""Butler API 聚合器（routes 域模块的纯装配点，conventions/4 §2.1）。

本文件不放端点、不放投影模型、不放业务判断——一业务域 = 一模块 =
一文件，域内自带投影模型与序列化器（红线 2 载体随域走）：
accounts（卡与凭据）/ apps（应用与导入）/ runs（运行台账）/ usage（用量雷达）。

include 顺序 = OpenAPI paths 首现顺序（契约指纹含 paths 键序，乱序即漂移）；
新端点先找域，域不存在则新建模块，禁止回塞本文件。
"""

from __future__ import annotations

from fastapi import APIRouter

from server.routes.accounts import router as accounts_router
from server.routes.apps import router as apps_router
from server.routes.runs import router as runs_router
from server.routes.usage import router as usage_router

router = APIRouter()
router.include_router(accounts_router)
router.include_router(apps_router)
router.include_router(runs_router)
router.include_router(usage_router)
