"""scripts 共用的極簡 CLI 參數解析(不引外部套件,模板維持零依賴)。"""

import sys


def flag_value(flag: str, default: str = "") -> str:
    """取「--flag 值」形式的參數;flag 不存在回 default,存在但缺值時退出並提示。"""
    if flag not in sys.argv:
        return default
    idx = sys.argv.index(flag)
    if idx + 1 >= len(sys.argv):
        raise SystemExit(f"{flag} 後面要接值。")
    return sys.argv[idx + 1]
