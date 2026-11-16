# butler 网关启动脚本（Windows / PowerShell 7+）
# 数据根：与主控共用项目内 data/database/butler.db（BUTLER_DB 与
# start-server.ps1 同款固化）——网关的路由账户名册/凭据池/计量库都在库里，
# 与主控不同库 = split-brain（账户查不到、计量互相不可见）；app 启动时
# 未设 BUTLER_DB 会告警，本脚本直接固化根除
# 用法：先起主控（scripts\start-server.ps1），再 powershell -File scripts\start-gateway.ps1
$env:BUTLER_DB = Join-Path $PSScriptRoot "..\data\database\butler.db"
Set-Location (Join-Path $PSScriptRoot "..")
# uv 解析（同 start-server.ps1：BUTLER_UV 覆盖 → ~/.local/bin → PATH）
$uv = $env:BUTLER_UV
if (-not $uv) {
    $localUv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path -LiteralPath $localUv) { $uv = $localUv }
}
if (-not $uv) { $uv = "uv" }
& $uv run python -m butler_gateway
