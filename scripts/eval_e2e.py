"""E2E 自動驗收:以 claude CLI headless 逐題實測,自動判分(取代人工採分)。

每題流程:claude -p <題目> --mcp-config <rosetta stdio> --allowedTools mcp__rosetta__*
→ 收最終回答 → 啟發式判分:
  - 清晰題(eval/questions.yaml):回答需含 expected 任一符號(不分大小寫),
    且**不應**反問(誤觸發統計,Phase 8 門檻:≤ 1/10)
  - 模糊題(eval/questions-vague.yaml):expect=clarify 需「像反問」
    (含問號/請確認 + 命中 ≥ 2 個 candidates);expect=answer 需含 must_include
判定為啟發式,邊界案例請人工複核(結果檔逐題附回答摘要供檢視)。

用法:.venv\\Scripts\\python.exe -X utf8 scripts\\eval_e2e.py [--set clear|vague|all]
     [--limit N] [--model MODEL]
輸出:eval/E2E-RESULT.md。注意:每題是一次真實 Claude session(有 API 成本,
zh 母本 10 題 + 模糊 5 題約需數分鐘),屬驗收工具,不掛 selftest。
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

import yaml

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PER_QUESTION_TIMEOUT = 600  # 秒

_CLARIFY_MARKERS = ("?", "？", "請問", "請確認", "確認一下", "釐清",
                    "想問的是哪", "哪一筆", "哪一間", "哪一個")


def _mcp_config_file() -> Path:
    config = {"mcpServers": {"rosetta": {
        "type": "stdio",
        "command": str(VENV_PYTHON),
        "args": [str(ROOT / "rosetta" / "kb_server.py")],
        "env": {"PYTHONUTF8": "1"},
    }}}
    path = Path(tempfile.mkdtemp()) / "mcp-rosetta.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def ask_claude(question: str, mcp_config: Path, model: str) -> str:
    """跑一次 headless claude,回傳最終文字回答(失敗時回錯誤描述)。"""
    prompt = (f"{question}\n\n(請用 rosetta MCP 工具查證後回答。"
              "問題已明確就直接回答;只有真的無法判斷我指哪個對象時,"
              "才在回答中提出釐清問題與選項。)")
    cmd = ["claude", "-p", prompt,
           "--mcp-config", str(mcp_config), "--strict-mcp-config",
           "--allowedTools", "mcp__rosetta",   # server 級允許(涵蓋 7 個 tools)
           "--max-turns", "20",
           "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", timeout=PER_QUESTION_TIMEOUT,
                              cwd=ROOT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(執行失敗:{type(exc).__name__})"
    if proc.returncode != 0:
        return f"(claude 退出碼 {proc.returncode}:{(proc.stderr or proc.stdout)[:200]})"
    try:
        return json.loads(proc.stdout).get("result", "")
    except json.JSONDecodeError:
        return proc.stdout.strip()


def looks_like_clarify(answer: str) -> bool:
    return any(marker in answer for marker in _CLARIFY_MARKERS)


def judge_clear(question: dict, answer: str) -> tuple[bool, str]:
    """清晰題:含任一 expected 符號 = 命中;另回報是否誤觸發反問。"""
    lowered = answer.lower()
    hit = any(e.lower() in lowered for e in question["expected"])
    note = "誤觸發反問" if looks_like_clarify(answer) and not hit else ""
    return hit, note


def judge_vague(question: dict, answer: str) -> tuple[bool, str]:
    if question["expect"] == "clarify":
        candidate_hits = sum(1 for c in question["candidates"] if c in answer)
        ok = looks_like_clarify(answer) and candidate_hits >= 2
        return ok, f"候選命中 {candidate_hits}"
    groups = question.get("must_include", [])
    misses = [g for g in groups if not any(k.lower() in answer.lower() for k in g)]
    return not misses, (f"缺 {misses}" if misses else "")


def main() -> int:
    which = sys.argv[sys.argv.index("--set") + 1] if "--set" in sys.argv else "all"
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else ""

    tasks: list[tuple[str, dict]] = []
    if which in ("clear", "all"):
        for q in yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8")):
            tasks.append(("clear", q))
    if which in ("vague", "all"):
        for q in yaml.safe_load((EVAL_DIR / "questions-vague.yaml").read_text(encoding="utf-8")):
            tasks.append(("vague", q))
    if limit:
        tasks = tasks[:limit]

    mcp_config = _mcp_config_file()
    lines = ["# E2E 自動驗收結果", "",
             f"- 產生:{time.strftime('%Y-%m-%d %H:%M:%S')};判定為啟發式,邊界請人工複核", ""]
    passed = mistrigger = 0
    for kind, q in tasks:
        question = q["zh"] if kind == "clear" else q["question"]
        print(f"[{q['id']}] {question}", flush=True)
        answer = ask_claude(question, mcp_config, model)
        if answer.startswith("(執行失敗") or answer.startswith("(claude 退出碼"):
            ok, note = False, "ERROR(未判分)"
        else:
            ok, note = (judge_clear(q, answer) if kind == "clear" else judge_vague(q, answer))
        passed += ok
        mistrigger += note == "誤觸發反問"
        excerpt = re.sub(r"\s+", " ", answer)[:150]
        lines.append(f"## {q['id']}({kind}){'✅' if ok else '❌'} {note}")
        lines.append(f"- 題目:{question}")
        lines.append(f"- 回答摘要:{excerpt}")
        lines.append("")
        print(f"  → {'PASS' if ok else 'FAIL'} {note}", flush=True)

    clear_total = sum(1 for k, _ in tasks if k == "clear")
    lines.insert(3, f"- 總計:{passed}/{len(tasks)} 通過;清晰題誤觸發反問 "
                    f"{mistrigger}/{clear_total}(門檻 ≤ 1/10)")
    (EVAL_DIR / "E2E-RESULT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{passed}/{len(tasks)} 通過 → eval/E2E-RESULT.md")
    return 0 if passed == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
