"""
播放器抽象接口
============
定义所有播放器实现必须遵循的契约
- QtPlayer: 使用 Qt 内置 QMediaPlayer
- CustomPlayer: 使用 PyAV + PyAudio 自实现
"""

from abc import ABC, abstractmethod
from PyQt6.QtCore import QObject, pyqtSignal


class IPlayer(QObject):
    """播放器抽象基类"""

    # ---- 信号定义 ----
    sig_frame_ready = pyqtSignal(object)      # 新帧就绪 → QImage
    sig_position_changed = pyqtSignal(int)    # 播放位置变化 → 毫秒
    sig_duration_changed = pyqtSignal(int)    # 视频总时长 → 毫秒
    sig_state_changed = pyqtSignal(bool)      # 播放状态变化 → True=播放中
    sig_finished = pyqtSignal()               # 播放结束
    sig_error = pyqtSignal(str)               # 错误信息

    def __init__(self, parent=None):
        super().__init__(parent)

    @abstractmethod
    def load(self, url: str) -> bool:
        """加载视频文件，成功返回 True"""

    @abstractmethod
    def play(self):
        """开始/恢复播放"""

    @abstractmethod
    def pause(self):
        """暂停播放"""

    @abstractmethod
    def stop(self):
        """停止播放并回到开头"""

    @abstractmethod
    def seek(self, ms: int):
        """跳转到指定毫秒位置"""

    @abstractmethod
    def is_playing(self) -> bool:
        """是否正在播放"""

    @abstractmethod
    def get_duration(self) -> int:
        """获取视频总时长 (ms)"""

    @abstractmethod
    def get_position(self) -> int:
        """获取当前播放位置 (ms)"""

    @abstractmethod
    def get_video_widget(self):
        """
        获取视频显示 Widget
        - Qt 播放器: 返回 QVideoWidget 容器
        - 自定义播放器: 返回 None（使用 QLabel 显示）
        """

    @abstractmethod
    def set_volume(self, volume: float):
        """设置音量 """
