"""
时间工具函数
============
- 毫秒 ↔ 可读时间字符串 转换
- 时间粒度对齐
- 业务逻辑：时间重叠检测
"""

import re
from datetime import datetime, timedelta

from utils.logger import get_logger

logger = get_logger("TimeUtil")

# 常用时间格式
TIME_PATTERN = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}"
BASE_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


# ==================== 时间对齐 ====================

def align_to_granularity(time_ms: int, granularity_ms: int) -> int:
    """
    四舍五入对齐到指定粒度
    例: align_to_granularity(730, 500) → 500
        align_to_granularity(760, 500) → 1000
    """
    if granularity_ms <= 0:
        return time_ms
    return ((time_ms + granularity_ms // 2) // granularity_ms) * granularity_ms


def floor_align_to_granularity(time_ms: int, granularity_ms: int) -> int:
    """向下对齐到指定粒度"""
    if granularity_ms <= 0:
        return time_ms
    return (time_ms // granularity_ms) * granularity_ms


def ceil_align_to_granularity(time_ms: int, granularity_ms: int) -> int:
    """向上对齐到指定粒度"""
    if granularity_ms <= 0:
        return time_ms
    return ((time_ms + granularity_ms - 1) // granularity_ms) * granularity_ms


# ==================== 时间转换 ====================

def time_ms_to_str(
    time_ms: int,
    base_time: str,
    out_format: str = "%Y-%m-%d %H:%M:%S.%f"
) -> str:
    """
    将视频内毫秒偏移转换为绝对时间字符串
    Args:
        time_ms:    视频内毫秒偏移
        base_time:  视频起始绝对时间 ("2024-01-01 12:00:00.000")
        out_format: 输出格式
    """
    if not base_time:
        return "0000-00-00 00:00:00.000"
    try:
        base_dt = _parse_time_str(base_time)
        target_dt = base_dt + timedelta(milliseconds=time_ms)
        result = target_dt.strftime(out_format)
        # %f 输出 6 位微秒，截取前 3 位为毫秒
        if out_format.endswith("%f"):
            result = result[:-3]
        return result
    except (ValueError, TypeError) as e:
        logger.warning(f"time_ms_to_str 失败: {e}")
        return base_time


def str_to_time_ms(time_str: str, base_time: str) -> int:
    """
    将绝对时间字符串转换为视频内毫秒偏移
    """
    try:
        dt1 = _parse_time_str(base_time)
        dt2 = _parse_time_str(time_str)
        delta = dt2 - dt1
        return int(delta.total_seconds() * 1000)
    except (ValueError, TypeError) as e:
        logger.warning(f"str_to_time_ms 失败: {e}")
        return 0


def ms_to_hms(ms) -> str:
    """
    毫秒数 → HH:MM:SS.mmm 格式字符串
    Args:
        ms: 毫秒数（int 或 float，None 时返回零值）
    """
    if ms is None:
        ms = 0
    ms = int(ms)
    if ms < 0:
        ms = 0

    total_seconds = ms // 1000
    ms_remain = ms % 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms_remain:03d}"


def parse_to_datetime(time_str: str, fmt: str) -> datetime:
    """解析时间字符串为 datetime 对象"""
    if "." not in time_str and "%f" in fmt:
        time_str += ".000"
    return datetime.strptime(time_str, fmt)


def standardize_time_str(time_str: str, input_fmt: str) -> str:
    """将时间字符串标准化为标准格式 YYYY-MM-DD HH:MM:SS.mmm"""
    dt = parse_to_datetime(time_str, input_fmt)
    return dt.strftime(BASE_FORMAT)[:-3]


# ==================== 业务逻辑 ====================

def check_overlap(
    new_start: int,
    new_end: int,
    records: list,
    ignore_index: int = -1
) -> bool:
    """
    检测新时间段是否与已有记录重叠
    Args:
        new_start:    新记录开始时间 (ms)
        new_end:      新记录结束时间 (ms)
        records:      已有记录列表
        ignore_index: 忽略的记录索引（编辑时排除自身）
    Returns:
        True 表示存在重叠
    """
    for i, record in enumerate(records):
        if i == ignore_index:
            continue
        s = record.get("start_raw")
        e = record.get("end_raw")
        if s is None or e is None:
            continue
        # 重叠判断: new_start <= e AND new_end >= s
        if new_start <= e and new_end >= s:
            return True
    return False


# ==================== 内部辅助 ====================

def _parse_time_str(time_str: str) -> datetime:
    """
    解析时间字符串，自动补齐毫秒位
    支持格式: "2024-01-01 12:00:00.123" 或 "2024-01-01 12:00:00"
    """
    if not time_str:
        raise ValueError("时间字符串为空")
    if "." not in time_str:
        time_str += ".000"
    return datetime.strptime(time_str, BASE_FORMAT)
