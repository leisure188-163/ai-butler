"""butler 网关进程包（R4，ADR-012）。

模块分工（一职责一模块，conventions/3）：
- config    绑定面/端口/鉴权 key 文件/路由表文件/主控地址的唯一解析口
- auth      随机 key 生成 + 0600 落盘 + Bearer 校验原语（G5 协议面挂载）
- control   主控通信：HTTP localhost 复用 server 契约 API（G1 = 可达性观测）
- routing   声明式路由表：模型→账户池有序映射，只读装载（G3，裁决 5/6）
- limiter   每账户并发限流闸门（G3；G5 协议面消费）
- platform       FastAPI 装配 + /health 健康可观测
"""
