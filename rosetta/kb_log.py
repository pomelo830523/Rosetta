"""kb server 的 logging 設定。

**stdio 模式下 stdout 是 MCP 協定通道,log 絕不能寫 stdout**——
一律走 stderr(Claude Code 會收進 %LOCALAPPDATA%\\claude-cli-nodejs\\Cache\\
<project>\\mcp-logs-*);KB_LOG_FILE 有設定時另寫一份到檔案(集中部署用)。

環境變數:
  KB_LOG_LEVEL = DEBUG | INFO(預設)| WARNING | ERROR
  KB_LOG_FILE  = log 檔路徑(未設定 = 只寫 stderr)

慣例:INFO 記每次 tool 呼叫與結果摘要、歧義訊號(S1~S3)觸發;
WARNING 記拒絕事件(白名單/敏感表/filter 驗證/路徑穿越/401)與引擎降級;
ERROR 記 DB 連線失敗等;DEBUG 才記完整查詢字串。
"""

import logging
import os
import sys

_LOGGER_NAME = "rosetta"


def setup() -> logging.Logger:
    """初始化並回傳 logger;重複呼叫不重複掛 handler。"""
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    level_name = os.environ.get("KB_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    log_file = os.environ.get("KB_LOG_FILE", "")
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("KB_LOG_FILE 無法開啟(%s),僅寫 stderr:%s", log_file, exc)
    logger.propagate = False
    return logger


def brief(text: str, limit: int = 60) -> str:
    """log 用的字串截斷(完整內容只在 DEBUG 記)。"""
    text = (text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"
