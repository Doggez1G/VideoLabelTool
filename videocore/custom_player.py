# videocore/custom_player.py
import av
import time
import numpy as np
from collections import deque

from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt, QMutex, QMutexLocker
from PyQt6.QtGui import QImage
from PyQt6.QtMultimedia import QAudioSink, QAudioFormat, QMediaDevices, QAudio

from .i_player import IPlayer
from utils.logger import get_logger

logger = get_logger("CustomPlayer")


class VideoDecoder(QThread):
    """流式解码 - 滑动窗口，避免内存爆炸"""
    sig_frame = pyqtSignal(object, int)
    sig_duration = pyqtSignal(int)
    sig_fps = pyqtSignal(float)
    sig_error = pyqtSignal(str)
    sig_ready = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._path = ""
        self._running = False
        self._frames = deque()
        self._mutex = QMutex()
        self._seek_request = None
        self._play_time = 0  # 当前播放时间（用于清理）
        self._duration_ms = 0
        self._fps = 30.0
        self._window_size = 10000  # 保留10秒缓冲（前后各5秒）

    def load(self, path: str):
        self._path = path
        with QMutexLocker(self._mutex):
            self._frames.clear()
            self._play_time = 0

    def stop(self):
        self._running = False
        self.wait(3000)

    def seek(self, target_ms: int):
        with QMutexLocker(self._mutex):
            self._seek_request = target_ms

    def set_play_time(self, current_ms: int):
        """更新播放位置，触发清理"""
        with QMutexLocker(self._mutex):
            self._play_time = current_ms
            # 清理窗口外的帧（只保留 play_time ± window_size/2）
            if len(self._frames) > 0:
                cutoff_low = current_ms - self._window_size // 2
                cutoff_high = current_ms + self._window_size // 2

                # 从头部移除太旧的帧
                while self._frames and self._frames[0][1] < cutoff_low:
                    self._frames.popleft()

                # 如果缓冲太大（异常），也从尾部清理
                while self._frames and self._frames[-1][1] > cutoff_high + 10000:
                    self._frames.pop()

    def get_frame(self, target_ms: int):
        with QMutexLocker(self._mutex):
            if not self._frames:
                return None

            # 简单查找（deque是序列，但索引访问是O(n)，不过通常缓冲不大）
            best = self._frames[0]
            best_diff = abs(best[1] - target_ms)

            for frame in self._frames:
                diff = abs(frame[1] - target_ms)
                if diff < best_diff:
                    best_diff = diff
                    best = frame

            return (best[0].copy(), best[1])

    def get_buffer_stats(self):
        with QMutexLocker(self._mutex):
            if not self._frames:
                return (0, 0, 0)
            return (len(self._frames), self._frames[0][1], self._frames[-1][1])

    def run(self):
        self._running = True
        container = None
        first_frame = True

        try:
            container = av.open(self._path)
            stream = container.streams.video[0]

            self._fps = float(stream.average_rate) if stream.average_rate else 30.0
            if stream.duration:
                self._duration_ms = int(float(stream.duration * stream.time_base) * 1000)

            self.sig_fps.emit(self._fps)
            self.sig_duration.emit(self._duration_ms)
            logger.info(f"视频解码器启动: {self._fps:.1f}fps")

            while self._running:
                # 处理Seek
                seek_to = None
                with QMutexLocker(self._mutex):
                    if self._seek_request is not None:
                        seek_to = self._seek_request
                        self._seek_request = None

                if seek_to is not None:
                    try:
                        tb = float(stream.time_base)
                        pts = int((seek_to / 1000.0) / tb)
                        container.seek(pts, stream=stream, backward=True)
                        with QMutexLocker(self._mutex):
                            self._frames.clear()
                        logger.info(f"Seek: {seek_to}ms")
                    except Exception as e:
                        logger.error(f"Seek失败: {e}")

                try:
                    for packet in container.demux(stream):
                        if not self._running:
                            break

                        for frame in packet.decode():
                            if not self._running:
                                break

                            try:
                                arr = frame.to_ndarray(format='rgb24')
                                if not arr.flags['C_CONTIGUOUS']:
                                    arr = np.ascontiguousarray(arr)

                                h, w, c = arr.shape
                                qimg = QImage(arr.data, w, h, c * w, QImage.Format.Format_RGB888)
                                qimg = qimg.copy()

                                pts_ms = int(float(frame.pts * stream.time_base) * 1000) if frame.pts else 0

                                with QMutexLocker(self._mutex):
                                    self._frames.append((qimg, pts_ms))

                                if first_frame:
                                    self.sig_frame.emit(qimg, pts_ms)
                                    self.sig_ready.emit()
                                    first_frame = False

                            except Exception as e:
                                logger.error(f"帧处理错误: {e}")

                            # 流量控制：缓冲超前播放位置超过15秒则等待
                            sleep_count = 0
                            while self._running and sleep_count < 100:  # 最多等1秒
                                with QMutexLocker(self._mutex):
                                    if not self._frames:
                                        break
                                    # 检查最后一帧是否超前播放位置太多
                                    ahead = self._frames[-1][1] - self._play_time
                                    if ahead < 15000:  # 超前小于15秒继续解码
                                        break
                                time.sleep(0.01)
                                sleep_count += 1

                except av.error.EOFError:
                    logger.info("视频EOF")
                    while self._running and self._seek_request is None:
                        time.sleep(0.1)
                    continue
                except Exception as e:
                    logger.error(f"解码错误: {e}")
                    time.sleep(0.1)

        except Exception as e:
            logger.error(f"致命错误: {e}", exc_info=True)
            self.sig_error.emit(str(e))
        finally:
            if container:
                container.close()
            logger.info("视频解码器退出")


class AudioDecoder(QThread):
    """音频流式解码"""
    sig_error = pyqtSignal(str)
    has_audio = False

    def __init__(self, volume_gain=2.0):
        super().__init__()
        self._path = ""
        self._running = False
        self._seek_request = None
        self._buffer = deque()
        self._mutex = QMutex()
        self._volume_gain = volume_gain
        self._play_time = 0
        self._window_size = 8000  # 音频保留8秒
        AudioDecoder.has_audio = False

    def load(self, path: str):
        self._path = path
        AudioDecoder.has_audio = False

    def stop(self):
        self._running = False
        self.wait(3000)

    def seek(self, target_ms: int):
        with QMutexLocker(self._mutex):
            self._seek_request = target_ms

    def set_play_time(self, current_ms: int):
        with QMutexLocker(self._mutex):
            self._play_time = current_ms
            # 清理旧音频
            cutoff = current_ms - 2000  # 保留2秒旧音频
            while self._buffer and self._buffer[0][1] < cutoff:
                self._buffer.popleft()

    def read(self, target_ms: int, max_packets=5):
        result = []
        with QMutexLocker(self._mutex):
            # 找到接近target_ms的包
            for pcm, pts in list(self._buffer):
                if abs(pts - target_ms) < 300:  # 300ms容差
                    result.append(pcm)
                    if len(result) >= max_packets:
                        break

            # 移除已读取的
            for _ in range(len(result)):
                if self._buffer:
                    self._buffer.popleft()
        return result

    def get_buffer_len(self):
        with QMutexLocker(self._mutex):
            return len(self._buffer)

    def run(self):
        self._running = True
        container = None

        try:
            container = av.open(self._path)

            if len(container.streams.audio) == 0:
                return

            AudioDecoder.has_audio = True
            stream = container.streams.audio[0]

            resampler = av.audio.resampler.AudioResampler(
                format='s16', layout='stereo', rate=48000
            )

            logger.info("音频解码器启动")

            while self._running:
                with QMutexLocker(self._mutex):
                    seek_target = self._seek_request
                    self._seek_request = None

                if seek_target is not None:
                    try:
                        tb = float(stream.time_base)
                        pts = int((seek_target / 1000.0) / tb)
                        container.seek(pts, stream=stream, backward=True)
                        with QMutexLocker(self._mutex):
                            self._buffer.clear()
                        logger.info(f"音频Seek: {seek_target}ms")
                    except Exception as e:
                        logger.error(f"音频Seek失败: {e}")

                try:
                    for packet in container.demux(stream):
                        if not self._running:
                            break

                        for frame in packet.decode():
                            if not self._running:
                                break

                            try:
                                resampled = resampler.resample(frame)
                                for rframe in resampled:
                                    samples = rframe.to_ndarray()

                                    if samples.dtype != np.int16:
                                        samples = samples.astype(np.int16)

                                    if self._volume_gain != 1.0:
                                        samples_float = samples.astype(np.float32) * self._volume_gain
                                        samples = np.clip(samples_float, -32768, 32767).astype(np.int16)

                                    pcm = samples.tobytes()
                                    pts_ms = int(float(rframe.pts * stream.time_base) * 1000) if rframe.pts else 0

                                    with QMutexLocker(self._mutex):
                                        self._buffer.append((pcm, pts_ms))
                            except Exception as e:
                                logger.warning(f"音频处理错误: {e}")

                            # 流量控制
                            sleep_count = 0
                            while self._running and sleep_count < 100:
                                with QMutexLocker(self._mutex):
                                    if not self._buffer:
                                        break
                                    ahead = self._buffer[-1][1] - self._play_time
                                    if ahead < 10000:  # 超前10秒
                                        break
                                time.sleep(0.01)
                                sleep_count += 1

                except av.error.EOFError:
                    logger.info("音频EOF")
                    while self._running and self._seek_request is None:
                        time.sleep(0.1)
                    continue
                except Exception as e:
                    logger.error(f"音频解码错误: {e}")
                    time.sleep(0.1)

        except Exception as e:
            logger.error(f"音频线程错误: {e}")
        finally:
            if container:
                container.close()


class CustomPlayer(IPlayer):
    """流式播放器 - 大缓冲，不缺帧"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._state = "Stopped"
        self._duration_ms = 0
        self._current_ms = 0
        self._fps = 30.0

        self._start_time = 0.0
        self._start_ms = 0

        self._video = VideoDecoder()
        self._audio = AudioDecoder(volume_gain=2.0)
        self._audio_sink = None
        self._audio_device = None

        self._timer = QTimer()
        self._timer.timeout.connect(self._update)
        self._timer.setInterval(16)

        self._volume = 1.0
        self._miss_count = 0  # 连续缺帧计数

        self._connect_signals()

    def _connect_signals(self):
        self._video.sig_frame.connect(self._on_frame)
        self._video.sig_duration.connect(self._on_duration)
        self._video.sig_ready.connect(self._on_ready)
        self._video.sig_error.connect(self.sig_error)
        self._audio.sig_error.connect(self.sig_error)

    def _on_frame(self, img, pts):
        self.sig_frame_ready.emit(img)
        self._current_ms = pts

    def _on_duration(self, ms):
        self._duration_ms = ms
        self.sig_duration_changed.emit(ms)

    def _on_ready(self):
        if self._state == "Loading":
            self._state = "Ready"
            self.sig_state_changed.emit(False)

    def _init_audio(self):
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(48000)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)

            devices = QMediaDevices.audioOutputs()
            if not devices:
                return False

            self._audio_sink = QAudioSink(devices[0], fmt)
            self._audio_sink.setVolume(self._volume)
            self._audio_device = self._audio_sink.start()
            return True
        except Exception as e:
            logger.error(f"音频初始化失败: {e}")
            return False

    def _stop_audio(self):
        if self._audio_sink:
            try:
                self._audio_sink.stop()
            except:
                pass
            self._audio_sink = None
        self._audio_device = None

    def load(self, url: str) -> bool:
        logger.info(f"加载: {url}")
        self.stop()

        try:
            probe = av.open(url)
            has_audio = len(probe.streams.audio) > 0
            probe.close()

            self._video.load(url)
            self._video.start()

            if has_audio:
                self._audio.load(url)
                self._audio.start()

            self._state = "Loading"
            return True
        except Exception as e:
            logger.error(f"加载失败: {e}")
            return False

    def play(self):
        if self._state not in ["Ready", "Paused"]:
            return

        if self._duration_ms <= 0:
            return

        self._state = "Playing"
        self._start_time = time.perf_counter()
        self._start_ms = self._current_ms
        self._miss_count = 0

        # 通知解码器当前位置
        self._video.set_play_time(self._current_ms)
        self._audio.set_play_time(self._current_ms)

        # 音频：暂停后重新初始化（解决无声问题）
        self._stop_audio()
        if AudioDecoder.has_audio:
            self._init_audio()

        self._timer.start()
        self.sig_state_changed.emit(True)
        logger.info(f"播放: {self._start_ms}ms")

    def pause(self):
        if self._state != "Playing":
            return

        self._state = "Paused"
        self._timer.stop()

        elapsed = (time.perf_counter() - self._start_time) * 1000
        self._current_ms = self._start_ms + int(elapsed)

        self._stop_audio()
        self.sig_state_changed.emit(False)

    def stop(self):
        if self._state == "Stopped":
            return

        self._state = "Stopped"
        self._timer.stop()

        self._stop_audio()
        self._video.stop()
        self._audio.stop()

        self._current_ms = 0

        self.sig_position_changed.emit(0)
        self.sig_state_changed.emit(False)

    def seek(self, ms: int):
        """跳转"""
        if self._state == "Stopped":
            return

        target = max(0, min(ms, self._duration_ms))
        was_playing = (self._state == "Playing")

        if was_playing:
            self.pause()

        logger.info(f"Seek: {target}ms")

        self._current_ms = target

        # 通知解码器新位置
        self._video.set_play_time(target)
        self._audio.set_play_time(target)

        # 发送Seek命令
        self._video.seek(target)
        self._audio.seek(target)

        # 等待解码就绪（短暂）
        time.sleep(0.1)

        # 显示帧
        frame = self._video.get_frame(target)
        if frame:
            img, pts = frame
            self.sig_frame_ready.emit(img)
            self.sig_position_changed.emit(pts)

        if was_playing:
            self.play()

    def _update(self):
        """更新"""
        if self._state != "Playing":
            return

        # 计算当前时间
        elapsed = (time.perf_counter() - self._start_time) * 1000
        current_ms = self._start_ms + int(elapsed)

        # 检查结束
        if current_ms >= self._duration_ms:
            self.sig_finished.emit()
            self.stop()
            return

        # 通知解码器当前位置（触发清理）
        self._video.set_play_time(current_ms)
        self._audio.set_play_time(current_ms)

        # 视频更新
        frame = self._video.get_frame(current_ms)
        if frame:
            img, pts = frame
            if pts != self._current_ms:
                self._current_ms = pts
                self.sig_frame_ready.emit(img)
                self.sig_position_changed.emit(pts)
            self._miss_count = 0
        else:
            self._miss_count += 1
            # 每30帧（约0.5秒）记录一次日志
            if self._miss_count % 30 == 1:
                count, start, end = self._video.get_buffer_stats()
                logger.debug(f"缺帧: target={current_ms}ms, 缓冲={count}帧 [{start}-{end}]")

        # 音频更新
        if self._audio_device and AudioDecoder.has_audio:
            try:
                free_bytes = self._audio_sink.bytesFree()
                if free_bytes > 4096:
                    pcm_list = self._audio.read(current_ms, max_packets=3)
                    for pcm in pcm_list:
                        self._audio_device.write(pcm)
            except Exception as e:
                logger.error(f"音频错误: {e}")

    def set_volume(self, volume: float):
        self._volume = max(0.0, min(1.0, volume))
        if self._audio_sink:
            try:
                self._audio_sink.setVolume(self._volume)
            except:
                pass

    def is_playing(self) -> bool:
        return self._state == "Playing"

    def get_duration(self) -> int:
        return self._duration_ms

    def get_position(self) -> int:
        return self._current_ms

    def get_video_widget(self):
        return None