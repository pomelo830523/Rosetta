"""kb server log 彙整報表:tool 用量/耗時、歧義訊號統計、拒絕與錯誤事件。

用途(維運 + Phase 8 調校數據源):
  - S3 檢索空手的 query 清單 = glossary 該補的詞(「缺詞再補」從被動變主動)
  - S2 觸發率 = 調校 _SCATTER_DELTA 門檻的依據(過高表示誤觸發擾人)
  - WARNING 拒絕事件 = 白名單/敏感表/filter 的探測紀錄

輸入:KB_LOG_FILE 產出的 log 檔(格式:YYYY-MM-DD HH:MM:SS LEVEL [rosetta] 訊息)。
用法:.venv\\Scripts\\python.exe -X utf8 scripts\\log_report.py [LOG檔] [--since YYYY-MM-DD]
     LOG 檔省略時用專案根的 rosetta-kb.log。輸出 markdown 到 stdout。
"""

from collections import Counter, defaultdict
from pathlib import Path
import re
import sys

import script_args

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "rosetta-kb.log"

_LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}) "
    r"(?P<level>DEBUG|INFO|WARNING|ERROR) \[rosetta\] (?P<msg>.*)$")
_TOOL_RE = re.compile(r"^tool=(?P<tool>\w+)\((?P<args>.*)\)→ (?P<chars>\d+) 字元,(?P<ms>\d+)ms$")
_S3_RE = re.compile(r"^S3 檢索空手 app=(?P<app>\S+) engine=(?P<engine>\S+) query=(?P<query>.*)$")
_S1_RE = re.compile(r"^S1 歧義訊號 app=(?P<app>\S+) query=(?P<query>.*?) concepts=(?P<concepts>.*)$")


def parse(path: Path, since: str) -> dict:
    stats: dict = {
        "calls": Counter(), "ms": defaultdict(list),
        "s1": [], "s2": 0, "s3": [],
        "warnings": Counter(), "errors": [], "lines": 0,
        "first": "", "last": "",
    }
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _LINE_RE.match(raw)
        if not m or (since and m["date"] < since):
            continue
        stats["lines"] += 1
        stats["last"] = f"{m['date']} {m['time']}"
        if not stats["first"]:
            stats["first"] = stats["last"]
        msg = m["msg"]
        if m["level"] == "ERROR":
            stats["errors"].append(msg)
            continue
        if m["level"] == "WARNING":
            # 以訊息開頭分類(「query_db_config 白名單外被拒 …」→ 前兩個詞)
            stats["warnings"][" ".join(msg.split()[:2])] += 1
            continue
        tool = _TOOL_RE.match(msg)
        if tool:
            stats["calls"][tool["tool"]] += 1
            stats["ms"][tool["tool"]].append(int(tool["ms"]))
            continue
        if msg.startswith("S2 結果分散"):
            stats["s2"] += 1
        elif (s3 := _S3_RE.match(msg)):
            stats["s3"].append((s3["app"], s3["query"]))
        elif (s1 := _S1_RE.match(msg)):
            stats["s1"].append((s1["app"], s1["query"], s1["concepts"]))
    return stats


def report(stats: dict) -> str:
    out = ["# Rosetta kb server log 報表", "",
           f"- 期間:{stats['first'] or '-'} ~ {stats['last'] or '-'}"
           f"(共 {stats['lines']} 行)", ""]

    out += ["## tool 用量與耗時", "", "| tool | 次數 | 平均 ms | 最大 ms |", "|---|---|---|---|"]
    for tool, count in stats["calls"].most_common():
        ms = stats["ms"][tool]
        out.append(f"| {tool} | {count} | {sum(ms) // len(ms)} | {max(ms)} |")

    searches = stats["calls"].get("search_code", 0)
    out += ["", "## 歧義訊號(Phase 8 調校數據)", "",
            f"- S1 glossary 多義:{len(stats['s1'])} 次",
            f"- S2 結果分散:{stats['s2']} 次"
            + (f"(觸發率 {stats['s2'] / searches:.0%},分母 search_code {searches} 次)"
               if searches else ""),
            f"- S3 檢索空手:{len(stats['s3'])} 次"]

    if stats["s3"]:
        out += ["", "### S3 空手 query(= glossary 補詞候選)", ""]
        for (app, query), count in Counter(stats["s3"]).most_common(20):
            out.append(f"- [{app}] {query}({count} 次)")
    if stats["s1"]:
        out += ["", "### S1 命中多概念的 query(檢視是否誤觸發)", ""]
        for app, query, concepts in stats["s1"][:20]:
            out.append(f"- [{app}] {query} → {concepts}")

    if stats["warnings"]:
        out += ["", "## 拒絕/警告事件", ""]
        for kind, count in stats["warnings"].most_common():
            out.append(f"- {kind}:{count} 次")
    if stats["errors"]:
        out += ["", "## 錯誤", ""]
        out += [f"- {e}" for e in stats["errors"][:20]]
    return "\n".join(out) + "\n"


def main() -> int:
    since = script_args.flag_value("--since")
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != since]
    path = Path(args[0]) if args else DEFAULT_LOG
    if not path.is_file():
        print(f"找不到 log 檔:{path}(先以 KB_LOG_FILE 啟動 server 產生)")
        return 1
    print(report(parse(path, since)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
