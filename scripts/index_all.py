"""批次索引:逐 AP(可選 git pull →)codegraph sync → 語意索引增量。

首次 codegraph init 是一次性手動步驟(QUICKSTART);本腳本只對已建圖的 AP
自動 sync。語意索引以 content-hash 增量,已最新的 AP 幾乎零成本,可掛排程/CI。

用法:.venv\\Scripts\\python.exe -X utf8 scripts\\index_all.py [--pull] [--rebuild] [--app NAME]
  --pull     先在各 AP 的 repo_root 跑 git pull(伺服器集中部署用)
  --rebuild  全量重建(換 model / 索引壞掉時)
  --app      只跑指定 AP(省略 = 全部)
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rosetta"))

import kb_config
import script_args
import semantic_index


def _git_pull(app: kb_config.AppContext) -> str:
    try:
        proc = subprocess.run(
            ["git", "pull", "--ff-only"], cwd=app.repo_root,
            capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"[{app.name}] git pull 失敗:{exc}"
    if proc.returncode != 0:
        return f"[{app.name}] git pull 失敗:{(proc.stderr or proc.stdout).strip()}"
    return f"[{app.name}] git pull:{proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else 'ok'}"


def _codegraph_sync(app: kb_config.AppContext) -> str:
    """已建圖的 AP 增量同步呼叫圖;sync 失敗只警告(舊圖仍可用),不擋語意索引。"""
    # Windows 上 npm 同時產生無副檔名 shell script 與 .cmd,前者不可執行 → 優先 .cmd
    exe = shutil.which("codegraph.cmd") or shutil.which("codegraph")
    if exe is None:
        return f"[{app.name}] 找不到 codegraph CLI,略過圖同步(圖可能過時)"
    try:
        proc = subprocess.run(
            [exe, "sync", str(app.repo_root)],
            capture_output=True, text=True, timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"[{app.name}] codegraph sync 失敗:{exc}(沿用舊圖)"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[:200]
        return f"[{app.name}] codegraph sync 失敗:{detail}(沿用舊圖)"
    return f"[{app.name}] codegraph sync 完成"


def main() -> int:
    pull = "--pull" in sys.argv
    rebuild = "--rebuild" in sys.argv
    only = script_args.flag_value("--app")

    config = kb_config.load_config()
    apps = [a for a in config.apps if not only or a.name.lower() == only.lower()]
    if not apps:
        print(f"沒有名為「{only}」的 app。可用:{', '.join(config.app_names())}")
        return 1

    failures = 0
    for app in apps:
        if pull:
            print(_git_pull(app))
        if not app.codegraph_db.is_file():
            print(f"[{app.name}] 缺 codegraph 圖({app.codegraph_db}),跳過語意索引;"
                  "請先在該 repo 跑一次 codegraph init(QUICKSTART 步驟 3)。")
            failures += 1
            continue
        print(_codegraph_sync(app))
        try:
            print(semantic_index.build(app, rebuild=rebuild))
        except Exception as exc:  # 單一 AP 失敗不擋其他 AP(批次跑一晚的前提)
            print(f"[{app.name}] 語意索引失敗:{exc}")
            failures += 1
            continue
        # glossary 防腐化檢測:DEAD 條目只警示不擋索引(對照表修復是人工作業)
        import glossary_lint
        _, lint_lines = glossary_lint.lint_app(app)
        print("\n".join(lint_lines))

    print(f"\n完成:{len(apps) - failures}/{len(apps)} 個 AP 成功")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
