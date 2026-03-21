"""
统一日志系统
============
功能：
- 同时输出到控制台和日志文件
- 文件自动轮转（默认 5MB × 3 个备份）
- 统一的日志格式：[时间][级别][模块] 消息
- 线程安全

用法：
    from utils.logger import get_logger
    logger = get_logger("ModuleName")
    logger.info("消息内容")
    logger.error("错误详情", exc_info=True)  # 附带异常堆栈
"""

import logging
import logging.handlers
import os
import sys


# ==================== 全局日志格式 ====================
LOG_FORMAT = "[%(asctime)s][%(levelname)-5s][%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE_NAME = "label_tool.log"


def setup_logging(log_dir: str = "logs", level: str = "DEBUG"):
    """
    初始化全局日志配置
    在程序启动时调用一次即可

    Args:
        log_dir:    日志文件存放目录
        level:      日志级别 ("DEBUG", "INFO", "WARNING", "ERROR")
    """
    # 创建日志目录
    os.makedirs(log_dir, exist_ok=True)

    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))

    # 避免重复添加 Handler（防止多次调用 setup_logging）
    if root_logger.handlers:
        return

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # ---- 控制台 Handler（INFO 及以上） ----
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ---- 文件 Handler（DEBUG 及以上，自动轮转） ----
    log_path = os.path.join(log_dir, LOG_FILE_NAME)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,   # 5MB
        backupCount=3,               # 保留 3 个备份
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    # 记录日志系统启动
    root_logger.info(f"日志系统初始化完成，日志文件: {os.path.abspath(log_path)}")

def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志器

    Args:
        name: 日志器名称，建议使用模块名（如 "CustomPlayer"）
    Returns:
        logging.Logger 实例
    """
    return logging.getLogger(name)
