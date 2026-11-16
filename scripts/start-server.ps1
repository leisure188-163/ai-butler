# butler server 启动脚本（Windows / PowerShell 7+）
# 数据根：项目内 data/database/butler.db（2026-11-16 迁移：本机文件虚拟化层
# 锁死 home 目录 sqlite 伴生文件，journal_mode=OFF + 项目内数据根根治；
# schema 导出见 data/sql/butler-schema.sql，schema 入库版本化、db 不入库）
# 用法：powershell -File scripts\start-server.ps1
$env:BUTLER_DB = Join-Path $PSScriptRoot "..\data\database\butler.db"
$env:DOUBAO_IDENTITY_PATH = Join-Path $PSScriptRoot "..\data\doubao_identity.json"
Set-Location (Join-Path $PSScriptRoot "..")
# uv 解析（2026-11-16 去机器特定硬编码）：BUTLER_UV 覆盖 → 本机
# ~/.local/bin（本机 PATH 首位 hermes uv 损坏，见 docs/STATUS.md 环境备忘）
# → 兜底 PATH 里的 uv
$uv = $env:BUTLER_UV
if (-not $uv) {
    $localUv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path -LiteralPath $localUv) { $uv = $localUv }
}
if (-not $uv) { $uv = "uv" }
& $uv run python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
