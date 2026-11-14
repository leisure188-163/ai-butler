"""出站适配器层（COLA infrastructure 层，ADR-001）。

承载技术细节：事件总线落地、SQLite 台账/审计、凭据保险库、调度器。
依赖方向恒定：engine → core（实现端口、回填领域词汇）；端只准经 bridge.py 触达。
"""
