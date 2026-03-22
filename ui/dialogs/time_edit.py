import re
from PyQt6.QtWidgets import *

# 注意这里需要导入 videocore 里的工具函数
from utils.time import time_ms_to_str, TIME_PATTERN

class TimePointEditDialog(QDialog):
    def __init__(self, parent, current_time_str, base_time, video_pos_ms, title="编辑时间"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(450, 250)
        self.current_time_str = current_time_str
        self.base_time = base_time
        self.video_pos_ms = video_pos_ms
        self.result_time = current_time_str
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"当前记录时间：{self.current_time_str}"))
        layout.addWidget(QLabel("新时间："))
        self.time_edit = QLineEdit(self.current_time_str)
        self.time_edit.setMinimumHeight(35)
        layout.addWidget(self.time_edit)

        use_current_btn = QPushButton("📎 使用当前视频播放位置的时间")
        use_current_btn.clicked.connect(self.use_video_time)
        layout.addWidget(use_current_btn)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.on_ok)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def use_video_time(self):
        video_time = time_ms_to_str(self.video_pos_ms, self.base_time)
        self.time_edit.setText(video_time)

    def on_ok(self):
        new_time = self.time_edit.text().strip()
        if not re.match(TIME_PATTERN, new_time):
            QMessageBox.warning(self, "错误", f"格式不正确！应为 YYYY-MM-DD HH:MM:SS.sss")
            return
        self.result_time = new_time
        self.accept()