# butler server 启动脚本（Windows / PowerShell 7+）
# 数据根：项目内 data/database/butler.db（2026-11-16 迁移：本机文件虚拟化层
# 锁死 home 目录 sqlite 伴生文件，journal_mode=OFF + 项目内数据根根治；
# schema 导出见 data/sql/*.sql（按域分置），schema 入库版本化、db 不入库）
# 用法：powershell -File scripts\start-server.ps1
$env:BUTLER_DB = Join-Path $PSScriptRoot "..\data\database\butler.db"
$env:DOUBAO_IDENTITY_PATH = Join-Path $PSScriptRoot "..\data\doubao_identity.json"

# 豆包 CDP 端口自动探测（2026-11-18）：本机豆包常以非 9222 的端口启动
# （实测 `--remote-debugging-port=9223`），而 doubao_cn 连接器缺省读 9222，
# 于是签到永远卡在 PENDING「调试端口不可达」。这里从运行中的豆包主进程命令行
# 抓真实端口；显式设了 DOUBAO_CDP_PORT（或连接器侧覆盖）就不动。
if (-not $env:DOUBAO_CDP_PORT) {
    $doubaoMain = Get-CimInstance Win32_Process -Filter "Name='Doubao.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match '--remote-debugging-port=(\d+)' } |
        Select-Object -First 1
    if ($doubaoMain -and $doubaoMain.CommandLine -match '--remote-debugging-port=(\d+)') {
        $env:DOUBAO_CDP_PORT = $Matches[1]
        Write-Host "豆包 CDP 端口自动探测: $($Matches[1])"
    }
}

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
