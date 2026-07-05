# NL Query KB 安裝腳本(Windows PowerShell 5.1+)
# 做四件事:建 venv → 裝依賴 → 印出 .mcp.json 範本(stdio 開發模式)→ 跑 selftest。
# 集中部署(HTTP)不需要 .mcp.json:設 KB_TRANSPORT=http 後直接啟動 kb_server.py。
# 用法:powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"   # 讓 pip/python 一律用 UTF-8,避開 cp950 地區編碼
$KbDir = $PSScriptRoot
$VenvPython = Join-Path $KbDir ".venv\Scripts\python.exe"

Write-Host "=== NL Query KB setup ($KbDir) ==="

# 1. venv(用啟動 setup 的 python 建;之後一律用 venv 絕對路徑,避開多 Python 的 -32000 陷阱)
if (-not (Test-Path $VenvPython)) {
    Write-Host "[1/4] 建立 .venv ..."
    python -m venv (Join-Path $KbDir ".venv")
    if ($LASTEXITCODE -ne 0) { throw "python -m venv 失敗:請確認 python 3.12+ 在 PATH。" }
} else {
    Write-Host "[1/4] .venv 已存在,略過"
}

# 2. 依賴
Write-Host "[2/4] 安裝依賴(requirements.txt)..."
& $VenvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $KbDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install 失敗。封閉環境請改用內部 pypi mirror 或離線 wheel。" }

# 3. .mcp.json 範本(kb 是獨立專案,server 服務多個 AP:
#    .mcp.json 屬於「要用這個 MCP 的各 AP 專案根」,由管理員放進去或手動合併)
Write-Host "[3/4] .mcp.json 範本(stdio 開發模式;放到各 AP 專案根,已有 .mcp.json 則手動合併):"
$ServerName = "nl-query-kb"
$ConfigPath = Join-Path $KbDir "kb.config.yaml"
if (Test-Path $ConfigPath) {
    $m = Select-String -Path $ConfigPath -Pattern '^server_name:\s*(\S+)' | Select-Object -First 1
    if ($m) { $ServerName = $m.Matches[0].Groups[1].Value }
}
$McpJson = @{
    mcpServers = @{
        $ServerName = @{
            type    = "stdio"
            command = $VenvPython
            args    = @((Join-Path $KbDir "kb_server.py"))
            env     = @{ PYTHONUTF8 = "1" }
        }
    }
} | ConvertTo-Json -Depth 5
Write-Host $McpJson

# 4. selftest(模板初始狀態沒有 selftest,略過;各團隊可仿 BestHouse 寫自己的)
$SelftestPath = Join-Path $KbDir "selftest.py"
if (Test-Path $SelftestPath) {
    Write-Host "[4/4] 執行 selftest ..."
    $env:PYTHONUTF8 = "1"
    & $VenvPython -X utf8 $SelftestPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "selftest 未全數通過:語意索引未建時屬正常,先跑 index_all.py 再重試。"
    }
} else {
    Write-Host "[4/4] 無 selftest.py,略過(建議仿 BestHouse 版為你的 AP 寫一份)"
}

Write-Host ""
Write-Host "=== 完成 ==="
Write-Host "後續:"
Write-Host "  1. 編輯 kb.config.yaml 填入你的 AP 區塊"
Write-Host "  2. 各 AP repo 跑 codegraph 建圖後,執行:.venv\Scripts\python.exe index_all.py"
Write-Host "  3. 開發模式:重啟 Claude Code 後 /mcp 應可看到 $ServerName"
Write-Host "  4. 集中部署:`$env:KB_TRANSPORT='http'; .venv\Scripts\python.exe kb_server.py"
Write-Host "     (KB_HTTP_HOST / KB_HTTP_PORT 可改綁定,預設 127.0.0.1:8600)"
