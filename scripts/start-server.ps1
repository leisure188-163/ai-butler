# butler server 启动脚本（Windows / PowerShell 7+）
# 数据根：项目内 data/database/butler.db（2026-11-16 迁移：本机文件虚拟化层
# 锁死 home 目录 sqlite 伴生文件，journal_mode=OFF + 项目内数据根根治；
# schema 导出见 data/sql/butler-schema.sql，schema 入库版本化、db 不入库）
# 用法：powershell -File scripts\start-server.ps1
$env:BUTLER_DB = Join-Path $PSScriptRoot "..\data\database\butler.db"
$env:DOUBAO_IDENTITY_PATH = Join-Path $PSScriptRoot "..\data\doubao_identity.json"
Set-Location (Join-Path $PSScriptRoot "..")
& "C:\Users\A29159\.local\bin\uv.exe" run python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
