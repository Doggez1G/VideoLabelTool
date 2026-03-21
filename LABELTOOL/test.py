# videocore/custom_player.py
import av
import time

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker, QTimer, Qt
from PyQt6.QtGui import QImage

from .i_player import IPlayer


# ==================== 解码线程 ====================
class SimpleDecoder(QThread):
    sig_frame = pyqtSignal(object, float)  # (QImage, pts_sec)
    sig_duration = pyqtSignal(float)
    sig_fps = pyqtSignal(float)  # 新增：发送真实帧率
    sig_error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._path = ""
        self._running = False

    def load(self, path):
        self._path = path

    def run(self):
        self._running = True
        container = None
        try:
            container = av.open(self._path)
            stream = container.streams.video[0]

            # 获取元数据
            dur = float(stream.duration * stream.time_base) if stream.duration else 0
            fps = float(stream.average_rate) if stream.average_rate > 0 else 30.0

            self.sig_duration.emit(dur)
            self.sig_fps.emit(fps)  # 发送真实 FPS

            for frame in container.decode(video=0):
                if not self._running: break

                img = frame.to_ndarray(format='bgr24')
                h, w, ch = img.shape
                qt_img = QImage(img.data, w, h, ch * w, QImage.Format.Format_BGR888)
                qt_img = qt_img.copy()

                pts = float(frame.pts * frame.time_base) if frame.pts else 0
                self.sig_frame.emit(qt_img, pts)

                # 稍微限流，防止内存爆炸
                time.sleep(0.001)

        except Exception as e:
            self.sig_error.emit(str(e))
        finally:
            if container: container.close()


# ==================== 主播放器 ====================
class CustomPlayer(IPlayer):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._is_playing = False
        self._duration_ms = 0
        self._current_ms = 0
        self._fps = 30.0

        # 帧列表：[(QImage, pts_ms), ...]
        self._frames = []

        # 播放控制
        self._start_system_time = 0  # 记录按下播放时的系统时间戳
        self._start_frame_idx = 0  # 记录按下播放时的帧索引

        # 组件
        self._decoder = SimpleDecoder()
        self._timer = QTimer()
        self._timer.timeout.connect(self._sync_update)  # 改名：同步更新

        # 连接信号
        self._decoder.sig_frame.connect(self._on_got_frame, Qt.ConnectionType.QueuedConnection)
        self._decoder.sig_duration.connect(self._on_dur)
        self._decoder.sig_fps.connect(self._on_fps)
        self._decoder.sig_error.connect(self.sig_error)

    def load(self, url: str) -> bool:
        self.stop()
        self._frames = []
        self._start_frame_idx = 0
        self._decoder.load(url)
        self._decoder.start()
        return True

    def play(self):
        if self._is_playing: return
        if not self._frames: return

        self._is_playing = True
        self.sig_state_changed.emit(True)

        # 【关键】记录基准：
        # 1. 现在的系统时间
        # 2. 现在看到的是第几帧
        self._start_system_time = time.perf_counter()
        self._start_frame_idx = self._get_current_idx()

        self._timer.start(16)  # 高频率刷新 (60Hz)，保证丝滑

    def pause(self):
        if not self._is_playing: return
        self._is_playing = False
        self.sig_state_changed.emit(False)
        self._timer.stop()

    def stop(self):
        self.pause()
        self._seek_to_idx(0)

    def seek(self, ms: int):
        if not self._frames: return

        was_playing = self._is_playing
        self.pause()

        # 找最接近的帧
        target_idx = 0
        min_diff = float('inf')
        for i, (img, pts) in enumerate(self._frames):
            diff = abs(pts - ms)
            if diff < min_diff:
                min_diff = diff
                target_idx = i

        self._seek_to_idx(target_idx)

        if was_playing:
            self.play()

    def _seek_to_idx(self, idx):
        """内部方法：跳转到指定索引"""
        idx = max(0, min(idx, len(self._frames) - 1))
        if 0 <= idx < len(self._frames):
            img, pts = self._frames[idx]
            self._current_ms = pts
            self.sig_frame_ready.emit(img)
            self.sig_position_changed.emit(pts)

    def _get_current_idx(self):
        """根据当前的 pts 反查索引"""
        for i, (img, pts) in enumerate(self._frames):
            if pts >= self._current_ms:
                return i
        return len(self._frames) - 1

    def is_playing(self) -> bool:
        return self._is_playing

    def get_duration(self) -> int:
        return self._duration_ms

    def get_position(self) -> int:
        return self._current_ms

    def get_video_widget(self):
        return None

    # ------------------- 内部逻辑 -------------------
    def _on_dur(self, sec):
        self._duration_ms = int(sec * 1000)
        self.sig_duration_changed.emit(self._duration_ms)

    def _on_fps(self, fps):
        self._fps = fps
        print(f"[Info] Video FPS: {fps}")

    def _on_got_frame(self, qimg, pts_sec):
        pts_ms = int(pts_sec * 1000)
        self._frames.append((qimg, pts_ms))

        # 自动显示第一帧
        if len(self._frames) == 1:
            self._seek_to_idx(0)

    def _sync_update(self):
        """
        核心同步逻辑：
        不再是 "到时间了就走一帧"，
        而是 "根据现在的系统时间，算出我应该看到第几帧"。
        """
        if not self._is_playing: return

        # 1. 计算过去了多少秒
        elapsed_sec = time.perf_counter() - self._start_system_time

        # 2. 计算理论上应该看到哪一帧
        # 理论帧索引 = 起始索引 + (过去的秒数 * 帧率)
        target_idx_float = self._start_frame_idx + (elapsed_sec * self._fps)
        target_idx = int(target_idx_float)

        # 3. 边界检查
        if target_idx >= len(self._frames):
            # 播放结束
            self._seek_to_idx(len(self._frames) - 1)
            self.sig_finished.emit()
            self.pause()
            return

        # 4. 只有当目标索引和当前显示的不一样时，才更新画面
        # 这样可以避免不必要的渲染
        current_idx = self._get_current_idx()
        if target_idx != current_idx and 0 <= target_idx < len(self._frames):
            self._seek_to_idx(target_idx)