"""
Qt 原生播放器
============
基于 QMediaPlayer + QVideoWidget
- 优点: 稳定性高、格式支持广泛、自动硬件加速
- 缺点: 依赖系统解码器，自定义程度较低

优化内容：
- 完善错误处理和日志
- 精确的状态管理
- 内存泄漏防护
"""

from PyQt6.QtCore import QUrl, Qt, QTimer
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from utils.logger import get_logger
from .i_player import IPlayer

logger = get_logger("QtPlayer")


class QtPlayer(IPlayer):
    """
    Qt原生媒体播放器包装类
    封装QMediaPlayer提供统一的IPlayer接口
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 创建媒体播放器核心
        self._player = QMediaPlayer(parent)
        self._audio_output = QAudioOutput(parent)
        self._player.setAudioOutput(self._audio_output)

        # 设置默认音量
        self._audio_output.setVolume(1.0)

        # 创建视频显示容器
        # 使用容器包装以便统一接口（get_video_widget返回容器）
        self._container = QWidget()
        self._container.setObjectName("qtVideoContainer")
        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(0, 0, 0, 0)

        self._video_widget = QVideoWidget()
        self._video_widget.setObjectName("videoWidget")
        layout.addWidget(self._video_widget)

        # 将视频输出关联到组件
        self._player.setVideoOutput(self._video_widget)

        # 连接Qt信号到我们的信号
        self._setup_signals()

        # 延迟删除标记，防止重复释放
        self._is_released = False

        logger.info("QtPlayer初始化完成")

    def _setup_signals(self):
        """配置信号连接"""
        # 位置变化（播放进度）
        self._player.positionChanged.connect(
            lambda pos: self.sig_position_changed.emit(pos)
        )

        # 时长变化（视频加载完成）
        self._player.durationChanged.connect(
            lambda dur: self.sig_duration_changed.emit(dur)
        )

        # 播放状态变化
        self._player.playbackStateChanged.connect(self._on_state_changed)

        # 媒体状态变化（加载、缓冲等）
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)

        # 错误处理
        self._player.errorOccurred.connect(self._on_error)

    def _on_state_changed(self, state):
        """
        播放状态变化处理
        QMediaPlayer.PlaybackState: StoppedState, PlayingState, PausedState
        """
        is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        self.sig_state_changed.emit(is_playing)

        logger.debug(f"Qt播放状态变化: {state.name}, is_playing={is_playing}")

        # 检测自然播放结束
        if state == QMediaPlayer.PlaybackState.StoppedState:
            pos = self._player.position()
            dur = self._player.duration()

            # 如果位置接近结尾（200ms容差），认为是自然结束
            if dur > 0 and pos >= dur - 200:
                logger.info("QtPlayer检测到播放自然结束")
                self.sig_finished.emit()

    def _on_media_status_changed(self, status):
        """媒体状态变化（用于调试和错误处理）"""
        status_names = {
            QMediaPlayer.MediaStatus.NoMedia: "无媒体",
            QMediaPlayer.MediaStatus.LoadingMedia: "加载中",
            QMediaPlayer.MediaStatus.LoadedMedia: "已加载",
            QMediaPlayer.MediaStatus.StalledMedia: "停滞",
            QMediaPlayer.MediaStatus.BufferingMedia: "缓冲中",
            QMediaPlayer.MediaStatus.BufferedMedia: "缓冲完成",
            QMediaPlayer.MediaStatus.EndOfMedia: "媒体结尾",
            QMediaPlayer.MediaStatus.InvalidMedia: "无效媒体"
        }
        status_str = status_names.get(status, f"未知状态({status})")
        logger.debug(f"Qt媒体状态: {status_str}")

    def _on_error(self, error, error_string):
        """错误处理"""
        error_msg = f"[{error.name}] {error_string}"
        logger.error(f"QtPlayer错误: {error_msg}")
        self.sig_error.emit(error_string)

    # ==================== IPlayer 接口实现 ====================

    def load(self, url: str) -> bool:
        """
        加载视频文件
        Args:
            url: 视频文件的本地路径
        Returns:
            始终返回True（实际加载是异步的，通过mediaStatusChanged通知）
        """
        logger.info(f"QtPlayer加载视频: {url}")
        self._player.setSource(QUrl.fromLocalFile(url))
        return True

    def play(self):
        """开始或恢复播放"""
        logger.debug("QtPlayer执行播放")
        self._player.play()

    def pause(self):
        """暂停播放"""
        logger.debug("QtPlayer执行暂停")
        self._player.pause()

    def stop(self):
        """停止播放（回到开头）"""
        logger.debug("QtPlayer执行停止")
        self._player.stop()
        self._player.setSource(QUrl())

    def seek(self, ms: int):
        """
        跳转到指定毫秒位置
        Qt的setPosition是异步操作，会触发positionChanged信号
        """
        logger.debug(f"QtPlayer执行Seek: {ms}ms")
        self._player.setPosition(ms)

    def is_playing(self) -> bool:
        """检查是否正在播放"""
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def get_duration(self) -> int:
        """获取视频总时长（毫秒）"""
        return self._player.duration()

    def get_position(self) -> int:
        """获取当前播放位置（毫秒）"""
        return self._player.position()

    def get_video_widget(self) -> QWidget:
        """
        返回视频显示组件
        返回的是包装容器，包含实际的QVideoWidget
        """
        return self._container

    def set_volume(self, volume: float):
        """
        设置音量（0.0 - 1.0）
        额外功能，不在IPlayer接口中但有用
        """
        try:
            self._audio_output.setVolume(volume)
            logger.debug(f"QtPlayer音量: {volume}")
        except Exception as e:
            logger.error(f"设置音量失败: {e}")

    def release_resources(self):
        """
        【关键修复】安全释放Qt多媒体资源
        必须在GUI线程调用，且遵循以下顺序：
        1. 停止播放
        2. 断开信号（防止回调到已删除对象）
        3. 移除VideoOutput（解除QMediaPlayer与QVideoWidget的关联）
        4. 从布局移除Widget
        5. 延迟删除对象（等待Qt事件循环处理）

        原因：QVideoWidget在Windows平台与DirectShow后端交互复杂，
        立即删除容易导致访问冲突（0xC0000005）
        """
        if self._is_released:
            logger.debug("QtPlayer资源已释放，跳过")
            return

        logger.info("开始释放QtPlayer资源")

        # 1. 确保停止播放
        try:
            self._player.stop()
            logger.debug("媒体播放器已停止")
        except Exception as e:
            logger.warning(f"停止播放器时异常: {e}")

        # 2. 断开所有信号连接（防止野指针回调）
        try:
            self._player.positionChanged.disconnect()
            self._player.durationChanged.disconnect()
            self._player.playbackStateChanged.disconnect()
            self._player.mediaStatusChanged.disconnect()
            self._player.errorOccurred.disconnect()
            logger.debug("信号已断开")
        except Exception as e:
            logger.debug(f"断开信号时（可能已断开）: {e}")

        # 3. 解除视频输出关联（必须在删除Widget之前）
        try:
            self._player.setVideoOutput(None)
            self._player.setAudioOutput(None)
            logger.debug("视频/音频输出已解除")
        except Exception as e:
            logger.warning(f"解除输出关联时异常: {e}")

        # 4. 从布局移除VideoWidget但不立即删除
        if self._video_widget:
            try:
                self._layout.removeWidget(self._video_widget)
                self._video_widget.setParent(None)
                logger.debug("VideoWidget已从布局移除")
            except Exception as e:
                logger.warning(f"移除Widget时异常: {e}")

        self._is_released = True

        # 5. 延迟删除对象（100ms后，在下次事件循环中执行）
        # 这是避免崩溃的关键：给Qt时间处理完所有待处理的绘制事件
        try:
            QTimer.singleShot(100, self._container.deleteLater)
            QTimer.singleShot(100, self._player.deleteLater)
            logger.debug("已安排延迟删除对象")
        except Exception as e:
            logger.error(f"安排延迟删除时异常: {e}")