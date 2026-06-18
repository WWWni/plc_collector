"""
日志配置模块
"""
import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(
    name: str = "plc_collector",
    level: str = "INFO",
    log_file: str = "logs/collector.log",
    max_bytes: int = 10485760,
    backup_count: int = 5,
) -> logging.Logger:
    """配置并返回logger实例"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件handler（带轮转）
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
