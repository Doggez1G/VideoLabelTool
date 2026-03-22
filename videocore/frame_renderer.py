"""
视频帧渲染器
============
将 QImage 缩放并居中渲染到 QLabel 上
- 保持宽高比
- 使用 FastTransformation 保证性能
"""

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QImage, QPixmap

from utils.logger import get_logger

logger = get_logger("FrameRenderer")


class FrameRenderer:
    """视频帧渲染器"""

    def __init__(self):
        pass

    def render(self, qimage: QImage, target_size: QSize) -> QPixmap:
        """
        将 QImage 渲染为适合目标尺寸的 QPixmap

        Args:
            qimage:      视频帧
            target_size: 目标显示区域尺寸
        Returns:
            缩放后的 QPixmap
        """
        if qimage is None or qimage.isNull():
            return QPixmap()

        # 缩放（保持宽高比，使用快速变换）
        scaled = qimage.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

        return QPixmap.fromImage(scaled)
