# 從 Rosetta 產出通用模板(單一事實來源:server code 只在這裡維護,
# 模板用本腳本重新產生,避免兩份 code 漂移)。
# 用法:powershell -ExecutionPolicy Bypass -File scripts\make_template.ps1 [-OutDir 路徑]

param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$KbDir = Split-Path $PSScriptRoot -Parent   # 本腳本在 scripts/,專案根是上一層
if ($OutDir -eq "") {
    $OutDir = Join-Path (Split-Path $KbDir -Parent) "nl-query-kb-template"
}

# server 核心(通用,直接複製到模板的 rosetta/)
$CoreFiles = @(
    "kb_server.py", "kb_config.py", "kb_log.py", "code_search.py", "glossary.py",
    "app_config.py", "db_config.py", "graph_db.py",
    "semantic_common.py", "semantic_search.py", "semantic_index.py"
)
# 維運腳本(複製到模板的 scripts/)
$ScriptFiles = @("index_all.py", "extract_glossary.py", "setup.ps1")
# 刻意排除(本站專屬):config/kb.config.yaml、config/glossary/、tests/、
# scripts/eval_retrieval.py(依賴 eval/ 題庫)、scripts/make_template.ps1、
# eval/、.venv/.semantic/.codegraph、code-kb-comparison.md

New-Item -ItemType Directory -Force $OutDir | Out-Null
New-Item -ItemType Directory -Force (Join-Path $OutDir "rosetta") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $OutDir "scripts") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $OutDir "config\glossary") | Out-Null

foreach ($f in $CoreFiles) {
    Copy-Item (Join-Path $KbDir "rosetta\$f") (Join-Path $OutDir "rosetta\$f") -Force
}
foreach ($f in $ScriptFiles) {
    Copy-Item (Join-Path $KbDir "scripts\$f") (Join-Path $OutDir "scripts\$f") -Force
}
Copy-Item (Join-Path $KbDir "requirements.txt") (Join-Path $OutDir "requirements.txt") -Force

# 模板專屬檔(template/ 目錄維護)
Copy-Item (Join-Path $KbDir "template\README.md") (Join-Path $OutDir "README.md") -Force
Copy-Item (Join-Path $KbDir "template\kb.config.yaml.example") (Join-Path $OutDir "config\kb.config.yaml.example") -Force

# 架設文件隨模板走
Copy-Item (Join-Path $KbDir "docs\QUICKSTART.md") (Join-Path $OutDir "QUICKSTART.md") -Force

# .gitignore(kb.config.yaml 與 glossary 是團隊資產,要進版控,不在此列)
$GitIgnore = @"
.venv/
.semantic/
__pycache__/
glossary.generated*.yaml
"@
[System.IO.File]::WriteAllText((Join-Path $OutDir ".gitignore"), $GitIgnore, (New-Object System.Text.UTF8Encoding($false)))

# glossary 目錄佔位說明
$GlossaryNote = @"
每 AP 一份對照表,檔名建議 <app>.yaml(kb.config.yaml 的 glossary 欄位指定,路徑相對於 config/)。
骨架:.venv\Scripts\python.exe -X utf8 scripts\extract_glossary.py --app <name>
格式範例見 QUICKSTART.md 步驟 4。
"@
[System.IO.File]::WriteAllText((Join-Path $OutDir "config\glossary\README.txt"), $GlossaryNote, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "模板已產出:$OutDir"
Get-ChildItem $OutDir -Recurse -File | ForEach-Object { $_.FullName.Substring($OutDir.Length + 1) }
