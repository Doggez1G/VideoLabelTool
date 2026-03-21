"""
配置文件管理
============
- 读取/写入 label_tool_config.json
- 提供默认值兜底
- 所有异常均记录日志
"""

import os
import json

from utils.logger import get_logger

logger = get_logger("Config")

CONFIG_FILE = "label_tool_config.json"

# 默认配置（所有配置项的权威默认值）
DEFAULT_CONFIG = {
    "granularity": 500,                                  # 时间粒度 (ms)
    "time_format": "%Y/%m/%d %H:%M:%S.%f",              # 保存时间格式
    "offset": 0,                                         # 全局时间偏移 (ms)
    "ocr_engine": "EasyOCR",                             # OCR 引擎
    "tesseract_path": r"D:\TesseractOCR\tesseract.exe",  # Tesseract 路径
    "theme": "dark",                                     # 界面主题
    "step_seconds": 5.0,                                 # 快进/快退步长 (秒)
    "player_type": "custom",                             # 播放器类型: "custom" 或 "qt"
}


def load_config() -> dict:
    """
    加载配置文件
    - 文件不存在时返回默认配置
    - 文件损坏时记录警告并返回默认配置
    - 已有的键会覆盖默认值，新增的键自动补充默认值
    """
    config = DEFAULT_CONFIG.copy()

    if not os.path.exists(CONFIG_FILE):
        logger.info(f"配置文件不存在，使用默认配置: {CONFIG_FILE}")
        return config

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
            config.update(saved)
        logger.info(f"配置加载成功: {CONFIG_FILE}")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"配置文件读取失败，使用默认配置: {e}")

    return config


def save_config(config: dict):
    """
    保存配置到文件
    """
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        logger.info(f"配置保存成功: {CONFIG_FILE}")
    except IOError as e:
        logger.error(f"配置保存失败: {e}")
