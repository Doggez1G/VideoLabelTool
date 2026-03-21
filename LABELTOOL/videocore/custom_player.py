"""
自定义播放器（正确版本）
==========================
特点：
1. 简洁的音视频同步机制
2. 基于系统时钟的精确同步
3. 避免复杂的缓冲区管理
4. 真正支持音频播放
"""

import av
import time
import numpy as np
from collections import deque
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt, QMutex, QMutexLocker
from PyQt6.QtGui import QImage
from PyQt6.QtMultimedia import QAudioSink, QAudioFormat, QMediaDevices

from utils.logger import get_logger
from .i_player import IPlayer

logger = get_logger("CustomPlayer")


class MediaDecoderThread(QThread):
    """
    媒体解码线程（音视频同步解码）
    特点：音视频在同一时间轴上解码，确保同步
    """
    sig_video_frame = pyqtSignal(object, int)  # (QImage, pts_ms)
    sig_audio_data = pyqtSignal(bytes, int)    # (pcm_data, pts_ms)
    sig_media_info = pyqtSignal(dict)          # 媒体信息：时长、帧率、采样率等
    sig_error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._path = ""
        self._running = False
        self._seek_target = -1
        self._mutex = QMutex()

    def load(self, path: str):
        """加载媒体文件"""
        logger.debug(f"[MediaDecoder] 加载: {path}")
        self._path = path

    def stop(self):
        """安全停止线程"""
        logger.debug("[MediaDecoder] 请求停止")
        self._running = False
        if not self.wait(2000):
            logger.warning("[MediaDecoder] 强制终止")
            self.terminate()

    def seek(self, target_ms: int):
        """请求跳转到指定位置"""
        logger.debug(f"[MediaDecoder] Seek请求: {target_ms}ms")
        self._seek_target = target_ms

    def run(self):
        """主解码循环"""
        self._running = True
        container = None

        try:
            logger.info(f"[MediaDecoder] 打开文件: {self._path}")
            container = av.open(self._path)

            # 获取媒体信息
            video_stream = container.streams.video[0] if container.streams.video else None
            audio_stream = container.streams.audio[0] if container.streams.audio else None

            info = {
                "has_video": video_stream is not None,
                "has_audio": audio_stream is not None,
                "duration": 0,
                "fps": 30.0,
                "sample_rate": 48000
            }

            if video_stream:
                if video_stream.duration:
                    info["duration"] = int(float(video_stream.duration * video_stream.time_base) * 1000)
                if video_stream.average_rate:
                    info["fps"] = float(video_stream.average_rate)

            if audio_stream:
                info["sample_rate"] = audio_stream.rate if audio_stream.rate else 48000

            self.sig_media_info.emit(info)
            logger.info(f"[MediaDecoder] 媒体信息: {info}")

            # 音频重采样器
            audio_resampler = None
            if audio_stream:
                audio_resampler = av.audio.resampler.AudioResampler(
                    format='s16', layout='stereo', rate=info["sample_rate"]
                )

            # 解码循环
            for packet in container.demux():
                if not self._running:
                    break

                # 处理跳转请求
                if self._seek_target >= 0:
                    try:
                        # 计算跳转位置
                        if video_stream:
                            tb = float(video_stream.time_base)
                            pts = int(self._seek_target / 1000.0 / tb)
                            container.seek(pts, stream=video_stream)
                        self._seek_target = -1
                        logger.debug("[MediaDecoder] Seek完成")
                    except Exception as e:
                        logger.error(f"[MediaDecoder] Seek失败: {e}")

                # 解码当前包
                try:
                    for frame in packet.decode():
                        if not self._running:
                            break

                        # 处理视频帧
                        if video_stream and hasattr(frame, 'to_ndarray'):
                            try:
                                # 转换为RGB
                                arr = frame.to_ndarray(format='rgb24')
                                if not arr.flags['C_CONTIGUOUS']:
                                    arr = np.ascontiguousarray(arr)

                                h, w, c = arr.shape
                                qimg = QImage(arr.data, w, h, c * w, QImage.Format.Format_RGB888)
                                qimg = qimg.copy()

                                # 计算时间戳
                                pts_ms = 0
                                if frame.pts is not None:
                                    pts_ms = int(float(frame.pts * frame.time_base) * 1000)

                                self.sig_video_frame.emit(qimg, pts_ms)

                            except Exception as e:
                                logger.error(f"[MediaDecoder] 视频帧处理错误: {e}")

                        # 处理音频帧
                        elif audio_stream and audio_resampler and hasattr(frame, 'to_ndarray'):
                            try:
                                # 重采样音频
                                resampled = audio_resampler.resample(frame)
                                for rframe in resampled:
                                    samples = rframe.to_ndarray()
                                    if samples.dtype != np.int16:
                                        samples = samples.astype(np.int16)

                                    pcm = samples.tobytes()
                                    pts_ms = 0
                                    if rframe.pts is not None:
                                        pts_ms = int(float(rframe.pts * rframe.time_base) * 1000)

                                    self.sig_audio_data.emit(pcm, pts_ms)

                            except Exception as e:
                                logger.warning(f"[MediaDecoder] 音频处理错误: {e}")

                except Exception as e:
                    logger.error(f"[MediaDecoder] 包解码错误: {e}")

        except Exception as e:
            logger.error(f"[MediaDecoder] 致命错误: {e}", exc_info=True)
            self.sig_error.emit(str(e))
        finally:
            if container:
                container.close()
            logger.info("[MediaDecoder] 线程结束")


class CustomPlayer(IPlayer):
    """
    自定义播放器（正确版本）
    基于系统时钟的音视频同步
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 播放状态
        self._state = "Stopped"
        self._duration_ms = 0
        self._current_ms = 0
        self._fps = 30.0
        self._sample_rate = 48000

        # 时间基准
        self._start_play_time = 0.0  # 播放开始时的系统时间（秒）
        self._start_media_time = 0   # 播放开始时的媒体时间（毫秒）

        # 帧缓冲（简单队列，避免复杂管理）
        self._video_frames = deque(maxlen=30)  # 最多缓冲30帧
        self._audio_buffer = deque(maxlen=100)  # 音频缓冲

        # 组件
        self._decoder = MediaDecoderThread()
        self._audio_sink = None
        self._audio_device = None

        # 定时器（视频刷新）
        self._video_timer = QTimer()
        self._video_timer.timeout.connect(self._update_video_frame)
        self._video_timer.setInterval(16)  # 约60Hz刷新

        # 定时器（音频推送）
        self._audio_timer = QTimer()
        self._audio_timer.timeout.connect(self._push_audio_data)
        self._audio_timer.setInterval(10)  # 10ms推送一次

        # 同步锁
        self._sync_mutex = QMutex()

        self._connect_signals()
        logger.info("[CustomPlayer] 初始化完成")

    def _connect_signals(self):
        """连接解码器信号"""
        self._decoder.sig_video_frame.connect(self._on_video_frame)
        self._decoder.sig_audio_data.connect(self._on_audio_data)
        self._decoder.sig_media_info.connect(self._on_media_info)
        self._decoder.sig_error.connect(self.sig_error)

    def _on_video_frame(self, qimg, pts_ms):
        """接收视频帧"""
        with QMutexLocker(self._sync_mutex):
            self._video_frames.append((qimg, pts_ms))

            # 首帧显示
            if len(self._video_frames) == 1 and self._state in ["Ready", "Playing"]:
                self._display_frame(qimg, pts_ms)

    def _on_audio_data(self, pcm_data, pts_ms):
        """接收音频数据"""
        with QMutexLocker(self._sync_mutex):
            self._audio_buffer.append((pcm_data, pts_ms))

    def _on_media_info(self, info):
        """接收媒体信息"""
        self._duration_ms = info.get("duration", 0)
        self._fps = info.get("fps", 30.0)
        self._sample_rate = info.get("sample_rate", 48000)

        self.sig_duration_changed.emit(self._duration_ms)
        self._state = "Ready"
        self.sig_state_changed.emit(False)

        logger.info(f"[CustomPlayer] 媒体就绪: 时长={self._duration_ms}ms, FPS={self._fps}")

    def _init_audio(self):
        """初始化音频输出"""
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(self._sample_rate)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)

            devices = QMediaDevices.audioOutputs()
            if not devices:
                logger.warning("[CustomPlayer] 无音频输出设备")
                return False

            self._audio_sink = QAudioSink(devs[0], fmt)
            self._audio_sink.setVolume(1.0)
            self._audio_device = self._audio_sink.start()

            logger.info(f"[CustomPlayer] 音频初始化: {self._sample_rate}Hz, 立体声")
            return True
        except Exception as e:
            logger.error(f"[CustomPlayer] 音频初始化失败: {e}")
            return False

    def load(self, url: str) -> bool:
        """加载媒体文件"""
        logger.info(f"[CustomPlayer] 加载: {url}")
        self.stop()

        try:
            self._decoder.load(url)
            self._decoder.start()
            return True
        except Exception as e:
            logger.error(f"[CustomPlayer] 加载失败: {e}")
            return False

    def play(self):
        """开始播放"""
        if self._state not in ["Ready", "Paused"]:
            logger.warning(f"[CustomPlayer] 无法播放，状态: {self._state}")
            return

        if self._duration_ms <= 0:
            logger.error("[CustomPlayer] 无法播放：时长未获取")
            return

        # 初始化音频（如果需要）
        if not self._audio_sink and self._audio_buffer:
            self._init_audio()

        # 记录播放基准
        self._start_play_time = time.perf_counter()
        self._start_media_time = self._current_ms

        # 启动定时器
        self._video_timer.start()
        if self._audio_sink:
            self._audio_timer.start()

        self._state = "Playing"
        self.sig_state_changed.emit(True)

        logger.info(f"[CustomPlayer] 开始播放: {self._current_ms}ms")

    def pause(self):
        """暂停播放"""
        if self._state != "Playing":
            return

        self._video_timer.stop()
        self._audio_timer.stop()

        if self._audio_sink:
            self._audio_sink.suspend()

        self._state = "Paused"
        self.sig_state_changed.emit(False)

        logger.info(f"[CustomPlayer] 暂停: {self._current_ms}ms")

    def stop(self):
        """停止播放"""
        logger.info("[CustomPlayer] 停止")

        self._video_timer.stop()
        self._audio_timer.stop()

        # 停止音频
        if self._audio_sink:
            self._audio_sink.stop()
            self._audio_sink = None
            self._audio_device = None

        # 停止解码
        self._decoder.stop()

        # 清空缓冲
        with QMutexLocker(self._sync_mutex):
            self._video_frames.clear()
            self._audio_buffer.clear()

        self._state = "Stopped"
        self._current_ms = 0
        self.sig_position_changed.emit(0)
        self.sig_state_changed.emit(False)

    def seek(self, ms: int):
        """跳转到指定位置"""
        if self._state == "Stopped":
            return

        # 边界保护
        target = max(0, min(ms, self._duration_ms))
        logger.info(f"[CustomPlayer] Seek: {target}ms")

        was_playing = (self._state == "Playing")
        if was_playing:
            self.pause()

        # 清空缓冲
        with QMutexLocker(self._sync_mutex):
            self._video_frames.clear()
            self._audio_buffer.clear()

        # 请求跳转
        self._decoder.seek(target)
        self._current_ms = target
        self.sig_position_changed.emit(target)

        # 等待一小段时间让解码器跳转
        time.sleep(0.05)

        if was_playing:
            self.play()

    def _update_video_frame(self):
        """更新视频帧（基于系统时钟）"""
        if self._state != "Playing":
            return

        # 计算当前应该播放的时间
        elapsed_ms = (time.perf_counter() - self._start_play_time) * 1000
        target_ms = self._start_media_time + elapsed_ms

        # 检查是否播放结束
        if target_ms >= self._duration_ms:
            logger.info("[CustomPlayer] 播放结束")
            self.sig_finished.emit()
            self.stop()
            return

        # 查找合适的帧
        with QMutexLocker(self._sync_mutex):
            if not self._video_frames:
                return

            # 查找最接近目标时间的帧
            best_frame = None
            best_diff = float('inf')

            for frame in self._video_frames:
                img, pts = frame
                diff = abs(pts - target_ms)
                if diff < best_diff:
                    best_diff = diff
                    best_frame = frame

            if best_frame and best_diff < 100:  # 100ms容差
                img, pts = best_frame
                if pts != self._current_ms:
                    self._display_frame(img, pts)

    def _display_frame(self, qimg, pts_ms):
        """显示视频帧"""
        self._current_ms = pts_ms
        self.sig_frame_ready.emit(qimg)
        self.sig_position_changed.emit(pts_ms)

    def _push_audio_data(self):
        """推送音频数据到设备"""
        if not self._audio_device or self._state != "Playing":
            return

        with QMutexLocker(self._sync_mutex):
            if not self._audio_buffer:
                return

            # 推送数据（最多3块）
            count = 0
            while self._audio_buffer and count < 3:
                pcm_data, pts = self._audio_buffer.popleft()
                try:
                    self._audio_device.write(pcm_data)
                    count += 1
                except Exception as e:
                    logger.warning(f"[CustomPlayer] 音频写入错误: {e}")
                    break

    def set_volume(self, vol: float):
        """设置音量"""
        if self._audio_sink:
            self._audio_sink.setVolume(max(0.0, min(1.0, vol)))

    def is_playing(self):
        return self._state == "Playing"

    def get_duration(self):
        return self._duration_ms

    def get_position(self):
        return self._current_ms

    def get_video_widget(self):
        return None
