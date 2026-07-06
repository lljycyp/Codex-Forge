import logging

from core.constants import LOG_DIR, LOG_PATH


def get_logger(name):
    """获取文件日志器；日志不能写入标准输出，否则会破坏 Electron 解析结果。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.addLevelName(logging.DEBUG, "调试")
    logging.addLevelName(logging.INFO, "信息")
    logging.addLevelName(logging.WARNING, "警告")
    logging.addLevelName(logging.ERROR, "错误")
    logging.addLevelName(logging.CRITICAL, "严重")
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
