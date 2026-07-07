"""AP config(application*.yml)查詢:攤平成 dot-key、敏感值遮罩、標註來源檔。

只讀不寫。回答「系統設定值是多少」時,答案來自當下磁碟上的 yml,不會過期。
"""

import re

import yaml

from pathlib import Path

from kb_config import AppContext

# 載入順序(後者覆蓋前者):application.yml/.yaml 基底 → 其他 profile 檔
# (字母序)→ application-local 最後(維持「local 覆蓋一切」的既有語意)。
# 實際生效取決於 Spring active profile,來源檔標註讓模型能說明覆蓋關係。
_BASE_STEMS = ("application",)
_LAST_STEMS = ("application-local",)


def config_files(app: AppContext) -> list[Path]:
    """該 AP 的 application*.yml / *.yaml 清單,依覆蓋順序排序。"""
    if not app.resources_dir.is_dir():
        return []
    found = sorted(
        set(app.resources_dir.glob("application*.yml"))
        | set(app.resources_dir.glob("application*.yaml")),
        key=lambda p: p.name.lower(),
    )

    def order(path: Path) -> tuple[int, str]:
        stem = path.stem.lower()
        if stem in _BASE_STEMS:
            return (0, stem)
        if stem in _LAST_STEMS:
            return (2, stem)
        return (1, stem)

    return sorted(found, key=order)

_SENSITIVE_KEY_RE = re.compile(
    r"password|passwd|secret|token|api[-_]?key|credential|private[-_]?key", re.IGNORECASE
)
_MASK = "****(敏感值已遮罩)"


def _flatten(node, prefix: str = "") -> dict[str, str]:
    """巢狀 dict → dot-key 平面 dict;list 以索引展開。"""
    flat: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            flat.update(_flatten(value, child_prefix))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            flat.update(_flatten(value, f"{prefix}[{i}]"))
    else:
        flat[prefix] = "" if node is None else str(node)
    return flat


def mask_value(key: str, value: str) -> str:
    """敏感 key 的值以遮罩取代;連在 url 內的 password 參數也一併處理。"""
    if _SENSITIVE_KEY_RE.search(key):
        return _MASK
    # 防呆:value 本身長得像連線字串時,遮罩其中的 password=xxx
    return re.sub(r"(password=)[^&;\s]+", r"\1****", value, flags=re.IGNORECASE)


# yml「key: value」行(key 可含 . - [] 引號);properties 的 key=value 由
# mask_value 的 password= 規則涵蓋
_YML_KV_RE = re.compile(r"""^(\s*["']?[\w.\-\[\]]+["']?\s*:\s+)(\S.*)$""")


def mask_text(text: str) -> str:
    """逐行遮罩 yml/properties 純文字中的敏感值(read_source 用)。

    行數不變,行號引用不受影響;非敏感行原樣保留。
    """
    masked_lines = []
    for line in text.splitlines():
        kv = _YML_KV_RE.match(line)
        if kv and _SENSITIVE_KEY_RE.search(kv.group(1)):
            masked_lines.append(kv.group(1) + _MASK)
        else:
            masked_lines.append(
                re.sub(r"(password=)[^&;\s]+", r"\1****", line, flags=re.IGNORECASE))
    return "\n".join(masked_lines)


def load_effective_config(app: AppContext) -> dict[str, tuple[str, str]]:
    """回傳 {dot_key: (value, source_file)};後載入的 profile 檔覆蓋基底。

    注意:實際生效與否取決於 Spring active profile,這裡呈現「local profile 啟用時」的視角,
    並在來源檔標註讓模型能說明覆蓋關係。
    """
    effective: dict[str, tuple[str, str]] = {}
    for path in config_files(app):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            effective[f"(parse-error:{path.name})"] = (str(exc), path.name)
            continue
        for key, value in _flatten(data).items():
            effective[key] = (value, path.name)
    return effective


def search_config(key_pattern: str, app: AppContext) -> str:
    """依 key 子字串(不分大小寫)過濾 config;空字串回傳全部。"""
    config = load_effective_config(app)
    if not config:
        return (f"讀不到任何 config 檔(找過 application*.yml / *.yaml,"
                f"目錄:{app.resources_dir})")

    needle = key_pattern.strip().lower()
    rows = [
        (key, mask_value(key, value), source)
        for key, (value, source) in sorted(config.items())
        if needle in key.lower()
    ]
    if not rows:
        return f"沒有符合「{key_pattern}」的 config key。可先不帶參數列出全部 key 再縮小範圍。"

    lines = [f"{key} = {value}    ← {source}" for key, value, source in rows]
    header = (
        f"共 {len(rows)} 筆(profile 檔覆蓋 application.yml 基底、local 最優先;"
        "敏感值已遮罩,遮罩不影響 key 本身的可見性):"
    )
    return header + "\n" + "\n".join(lines)
