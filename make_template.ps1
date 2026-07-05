# 從 Rosetta 產出通用模板(單一事實來源:server code 只在這裡維護,
# 模板用本腳本重新產生,避免兩份 code 漂移)。
# 用法:powershell -ExecutionPolicy Bypass -File make_template.ps1 [-OutDir 路徑]

param(
    [string]$OutDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "nl-query-kb-template")
)

$ErrorActionPreference = "Stop"
$KbDir = $PSScriptRoot

# server code(通用,直接複製)
$CodeFiles = @(
    "kb_server.py", "kb_config.py", "code_search.py", "glossary.py",
    "app_config.py", "db_config.py", "graph_db.py",
    "semantic_common.py", "semantic_search.py", "semantic_index.py",
    "index_all.py", "extract_glossary.py",
    "requirements.txt", "setup.ps1"
)
# 刻意排除(本站專屬):kb.config.yaml、glossary/、selftest*.py、
# eval_retrieval.py(依賴 eval/ 題庫)、eval/、.venv/.semantic/.codegraph、
# code-kb-comparison.md

New-Item -ItemType Directory -Force $OutDir | Out-Null
New-Item -ItemType Directory -Force (Join-Path $OutDir "glossary") | Out-Null

foreach ($f in $CodeFiles) {
    Copy-Item (Join-Path $KbDir $f) (Join-Path $OutDir $f) -Force
}

# 模板專屬檔(template/ 目錄維護)
Copy-Item (Join-Path $KbDir "template\README.md") (Join-Path $OutDir "README.md") -Force
Copy-Item (Join-Path $KbDir "template\kb.config.yaml.example") (Join-Path $OutDir "kb.config.yaml.example") -Force

# 兩份文件隨模板走
$DocsDir = Join-Path $KbDir "docs"
Copy-Item (Join-Path $DocsDir "QUICKSTART.md") (Join-Path $OutDir "QUICKSTART.md") -Force
Copy-Item (Join-Path $DocsDir "USER-GUIDE.md") (Join-Path $OutDir "USER-GUIDE.md") -Force

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
每 AP 一份對照表,檔名建議 <app>.yaml(kb.config.yaml 的 glossary 欄位指定)。
骨架:..\.venv\Scripts\python.exe -X utf8 ..\extract_glossary.py --app <name>
格式範例見 QUICKSTART.md 步驟 4。
"@
[System.IO.File]::WriteAllText((Join-Path $OutDir "glossary\README.txt"), $GlossaryNote, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "模板已產出:$OutDir"
Get-ChildItem $OutDir -Recurse -File | ForEach-Object { $_.FullName.Substring($OutDir.Length + 1) }
