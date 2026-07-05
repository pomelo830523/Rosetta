"""glossary 的載入、比對與 query 展開(業務用語 → IT 用語的對照層)。

每次查詢即時重讀 YAML(檔案小),編輯後不需重啟 server。
aliases 可為平面 list(視為 zh)或分語言 dict {zh, en, de, ja};
比對:子字串、en/de 不分大小寫。
"""

from dataclasses import dataclass
from pathlib import Path
import re

import yaml

ALIAS_LANGS = ("zh", "en", "de", "ja")

# camelCase / PascalCase / SNAKE_CASE 都拆成小寫單詞
_WORD_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    aliases: tuple[tuple[str, str], ...]  # ((lang, alias), ...)
    it_terms: tuple[str, ...]
    note: str

    def aliases_of(self, lang: str) -> tuple[str, ...]:
        return tuple(a for l, a in self.aliases if l == lang)

    def all_aliases(self) -> tuple[str, ...]:
        return tuple(a for _, a in self.aliases)


def _parse_aliases(raw) -> tuple[tuple[str, str], ...]:
    """平面 list 視為 zh;dict 依語言收集。未知語言 key 忽略(不炸 server)。"""
    pairs: list[tuple[str, str]] = []
    if isinstance(raw, list):
        pairs = [("zh", str(a)) for a in raw if a]
    elif isinstance(raw, dict):
        for lang in ALIAS_LANGS:
            for a in raw.get(lang) or []:
                if a:
                    pairs.append((lang, str(a)))
    return tuple(pairs)


def load_glossary(path: Path) -> list[GlossaryEntry]:
    """讀取指定的 glossary yaml(per-app);檔案不存在或格式錯誤時回空表(不讓搜尋整個失效)。"""
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError:
        return []
    entries: list[GlossaryEntry] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("term"):
            continue
        entries.append(GlossaryEntry(
            term=str(item["term"]),
            aliases=_parse_aliases(item.get("aliases")),
            it_terms=tuple(str(t) for t in (item.get("it_terms") or [])),
            note=str(item.get("note") or ""),
        ))
    return entries


def match_entries(query: str, entries: list[GlossaryEntry]) -> list[GlossaryEntry]:
    """term 或任一語言的 alias 出現在 query 中(en/de 不分大小寫)即命中。"""
    q = query.strip()
    q_lower = q.lower()
    matched = []
    for entry in entries:
        candidates = (entry.term, *entry.all_aliases())
        if any(c and c.lower() in q_lower for c in candidates):
            matched.append(entry)
    return matched


def split_identifier(identifier: str) -> set[str]:
    """把 IT 識別字拆成小寫單詞:HouseService.calculateScore → {house, service, calculate, score}。"""
    return {w.lower() for w in _WORD_RE.findall(identifier) if len(w) >= 3}


def expand_query(query: str, path: Path) -> tuple[set[str], list[GlossaryEntry]]:
    """依 glossary 展開查詢:回傳 (額外英文比對詞, 命中的條目)。

    命中「不含車位單價」時,額外詞會包含 calculate/price/ping/parking/... ,
    讓純口語(任一語言)也能比對到英文 identifier。
    """
    entries = load_glossary(path)
    matched = match_entries(query, entries)
    extra_terms: set[str] = set()
    for entry in matched:
        for it_term in entry.it_terms:
            extra_terms |= split_identifier(it_term)
    return extra_terms, matched


def format_entries(entries: list[GlossaryEntry]) -> str:
    """把條目排版成給模型讀的文字(alias 顯示 zh/en/de;ja 只給數量,不顯示原文)。"""
    parts = []
    for e in entries:
        lines = [f"### {e.term}"]
        shown = [a for lang in ("zh", "en", "de") for a in e.aliases_of(lang)]
        if shown:
            lines.append(f"- 同義詞:{'、'.join(shown)}")
        ja_count = len(e.aliases_of("ja"))
        if ja_count:
            lines.append(f"- (另有 ja 同義詞 {ja_count} 則,存於資料檔)")
        lines.append(f"- IT 對應:{', '.join(e.it_terms)}")
        if e.note:
            lines.append(f"- 說明:{e.note}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
