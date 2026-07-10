"""glossary 骨架萃取腳本(Phase 1 bootstrap / 企業化 pipeline 的雛形)。

掃描 backend entity 的 @Table / @Column / enum 常數與其上方的 JavaDoc 中文註解,
產出 glossary.generated.yaml 骨架:IT 詞自動填入,aliases 留白待人工補使用者口語。

用法:python scripts\\extract_glossary.py [--app NAME]
輸出:glossary.generated.<app>.yaml(在專案根,供人工挑選合併進該 app 的 glossary,不直接覆蓋)
entity 目錄來自 kb.config.yaml 的 entity_dir(per-app)。
"""

from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rosetta"))

import kb_config
import script_args

_TABLE_RE = re.compile(r'@Table\(name\s*=\s*"([A-Z_]+)"\)')
_COLUMN_RE = re.compile(
    r'(?:/\*\*\s*(?P<doc>.*?)\s*\*/\s*)?'          # 可選的 JavaDoc(單行)
    r'@Column\(name\s*=\s*"(?P<column>[A-Z_]+)"',
    re.DOTALL,
)
_ENUM_RE = re.compile(r"^\s*([A-Z][A-Z_]+)\s*[,;]\s*(?://\s*(.*))?$", re.MULTILINE)


def extract_file(path: Path) -> list[dict]:
    """從單一 entity/enum 檔萃取條目骨架。"""
    text = path.read_text(encoding="utf-8")
    class_name = path.stem
    items: list[dict] = []

    table_match = _TABLE_RE.search(text)
    if table_match:
        items.append({
            "term": f"(待命名:{table_match.group(1)})",
            "aliases": [],
            "it_terms": [table_match.group(1), class_name],
            "note": f"DB table,entity 為 {class_name}",
        })

    for match in _COLUMN_RE.finditer(text):
        doc = (match.group("doc") or "").strip().replace("\n", " ")
        # JavaDoc 內的中文說明是最好的 term 候選;沒有就留待人工命名
        term = doc if any("一" <= c <= "鿿" for c in doc) else f"(待命名:{match.group('column')})"
        items.append({
            "term": term,
            "aliases": [],
            "it_terms": [match.group("column")],
            "note": "",
        })

    if "enum " in text:
        for match in _ENUM_RE.finditer(text):
            items.append({
                "term": f"(待命名:{match.group(1)})",
                "aliases": [],
                "it_terms": [f"{class_name}.{match.group(1)}"],
                "note": (match.group(2) or "").strip(),
            })
    return items


def to_yaml(items: list[dict]) -> str:
    """不依賴 yaml dumper 的簡單輸出(欄位固定、順序可控)。"""
    lines = [
        "# 由 extract_glossary.py 自動產生的骨架——請人工挑選、補 aliases 後併入 glossary.yaml",
        "# (待命名:X)表示機器無法判斷業務用語,需人工命名或捨棄",
        "",
    ]
    for item in items:
        term = item["term"].replace("'", "''")  # 引號跳脫:term 常含「:」(如「說明:運費」)會炸 YAML
        lines.append(f"- term: '{term}'")
        lines.append("  aliases: []  # TODO 人工補使用者口語")
        lines.append(f"  it_terms: [{', '.join(item['it_terms'])}]")
        note = item["note"].replace("'", "''")
        lines.append(f"  note: '{note}'")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    app, error = kb_config.resolve_app(script_args.flag_value("--app"))
    if app is None:
        raise SystemExit(error)
    if app.entity_dir is None or not app.entity_dir.exists():
        raise SystemExit(f"app「{app.name}」的 entity_dir 未設定或不存在:{app.entity_dir}")

    items: list[dict] = []
    for path in sorted(app.entity_dir.rglob("*.java")):
        items.extend(extract_file(path))
    output_path = kb_config.ROOT_DIR / f"glossary.generated.{app.name}.yaml"
    output_path.write_text(to_yaml(items), encoding="utf-8")
    print(f"已產出 {output_path.name}:{len(items)} 條骨架(entity 來源:{app.entity_dir})")


if __name__ == "__main__":
    main()
