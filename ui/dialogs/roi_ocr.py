import os
import re
import cv2
import easyocr

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

from utils.time import TIME_PATTERN

# 尝试导入Tesseract
try:
    import pytesseract
except ImportError:
    pytesseract = None


class ROIIdentifyWindow(QDialog):
    def __init__(self, parent, first_frame, config, window_title="首帧时钟识别"):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setModal(True)
        self.setMinimumSize(1200, 850)
        self.original_frame = first_frame.copy()
        self.frame_h, self.frame_w = first_frame.shape[:2]
        self.final_text = ""
        self.config = config

        self.scale = min(1.0, 900 / self.frame_w, 650 / self.frame_h)
        self.scaled_w = int(self.frame_w * self.scale)
        self.scaled_h = int(self.frame_h * self.scale)
        self.scaled_frame = cv2.resize(first_frame, (self.scaled_w, self.scaled_h), interpolation=cv2.INTER_CUBIC)
        self.roi_start = None
        self.roi_end = None
        self.current_roi_data = None

        # 初始化 OCR
        self.reader_easyocr = None
        if config.get('ocr_engine') == 'EasyOCR':
            try:
                self.reader_easyocr = easyocr.Reader(['ch_sim', 'en'], gpu=False)
            except Exception as e:
                print(f"EasyOCR init failed: {e}")

        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("<b>画面（请框选时间区域）</b>"))
        self.full_frame_label = QLabel()
        self.full_frame_label.setFixedSize(self.scaled_w, self.scaled_h)
        self.full_frame_label.setStyleSheet("border: 2px solid #aaa; background-color: black;")
        self.update_full_frame()
        left_layout.addWidget(self.full_frame_label)
        left_layout.addStretch()

        right_layout = QVBoxLayout()
        right_layout.setSpacing(15)
        self.preview_label = QLabel("框选预览")
        self.preview_label.setFixedSize(320, 200)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background-color: #f0f0f0;")
        self.result_edit = QLineEdit()
        self.result_edit.setPlaceholderText(f"格式：YYYY-MM-DD HH:MM:SS.sss")
        self.result_edit.setMinimumHeight(35)
        self.identify_btn = QPushButton("识别选中区域")
        self.identify_btn.setEnabled(False)
        self.identify_btn.setMinimumHeight(40)
        self.identify_btn.clicked.connect(self.identify_roi_text)
        self.reset_btn = QPushButton("重置框选")
        self.reset_btn.clicked.connect(self.reset_roi)
        btn_group = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_group.button(QDialogButtonBox.StandardButton.Ok).setText("确认")
        btn_group.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btn_group.accepted.connect(self.on_confirm)
        btn_group.rejected.connect(self.reject)

        right_layout.addWidget(QLabel("区域预览："))
        right_layout.addWidget(self.preview_label)
        right_layout.addWidget(QLabel("时间结果："))
        right_layout.addWidget(self.result_edit)
        right_layout.addWidget(self.identify_btn)
        right_layout.addWidget(self.reset_btn)
        right_layout.addStretch()
        right_layout.addWidget(btn_group)

        main_layout.addLayout(left_layout, stretch=3)
        main_layout.addLayout(right_layout, stretch=1)

    def update_full_frame(self):
        display_frame = self.scaled_frame.copy()
        if self.roi_start and self.roi_end:
            x1, y1 = self.roi_start
            x2, y2 = self.roi_end
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.full_frame_label.setPixmap(QPixmap.fromImage(qt_img))

    def update_roi_preview(self):
        if not self.roi_start or not self.roi_end:
            self.preview_label.setText("请框选时钟区域")
            self.identify_btn.setEnabled(False)
            return
        x1_s = min(self.roi_start[0], self.roi_end[0])
        y1_s = min(self.roi_start[1], self.roi_end[1])
        x2_s = max(self.roi_start[0], self.roi_end[0])
        y2_s = max(self.roi_start[1], self.roi_end[1])
        x1 = int(x1_s / self.scale)
        y1 = int(y1_s / self.scale)
        x2 = int(x2_s / self.scale)
        y2 = int(y2_s / self.scale)
        if x2 - x1 < 10 or y2 - y1 < 10: return
        roi = self.original_frame[y1:y2, x1:x2]
        self.current_roi_data = roi
        preview = cv2.resize(roi, (320, 200), interpolation=cv2.INTER_CUBIC)
        rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.preview_label.setPixmap(QPixmap.fromImage(qt_img))
        self.identify_btn.setEnabled(True)

    def preprocess_image(self, img):
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        img = cv2.fastNlMeansDenoising(img, h=10)
        img = cv2.convertScaleAbs(img, alpha=1.2, beta=0)
        return img

    def identify_roi_text(self):
        if not hasattr(self, 'current_roi_data') or self.current_roi_data is None:
            return

        roi = self.current_roi_data
        processed = self.preprocess_image(roi)
        full_text = ""

        engine = self.config.get('ocr_engine', 'EasyOCR')

        try:
            if engine == 'EasyOCR':
                if self.reader_easyocr:
                    results = self.reader_easyocr.readtext(processed, detail=0, paragraph=False)
                    if results:
                        full_text = " ".join(results)
            elif engine == 'Tesseract':
                if pytesseract is None:
                    QMessageBox.warning(self, "错误", "pytesseract 未安装，请 pip install pytesseract")
                    return
                tess_path = self.config.get('tesseract_path', '')
                if tess_path and os.path.exists(tess_path):
                    pytesseract.pytesseract.tesseract_cmd = tess_path

                custom_config = r'--oem 3 --psm 11'
                full_text = pytesseract.image_to_string(processed, config=custom_config)

        except Exception as e:
            print(f"OCR Error: {e}")
            self.result_edit.setText(f"识别出错: {str(e)}")
            return

        clean_text = re.sub(r'\s+', '', full_text)
        time_chars = re.sub(r'[^\d\-:\.]', '', full_text)
        search_space = [full_text, clean_text, time_chars]

        found_time = None
        for text in search_space:
            loose_pattern = r'(\d{4}.{0,5}\d{2}.{0,5}\d{2}.{0,5}\d{2}.{0,5}\d{2}.{0,5}\d{2}.{0,5}\d{3})'
            candidates = re.findall(loose_pattern, text)
            for cand in candidates:
                refined = re.sub(r'[^\d\-:\.]', '', cand)
                matches = re.findall(TIME_PATTERN, refined)
                if matches:
                    found_time = matches[0]
                    break
            if found_time:
                break

        if found_time:
            self.result_edit.setText(found_time)
            self.result_edit.setFocus()
            return

        self.result_edit.setText(full_text if full_text else "无法识别，请手动输入")
        self.result_edit.setFocus()
        self.result_edit.selectAll()

    def reset_roi(self):
        self.roi_start = None
        self.roi_end = None
        self.result_edit.clear()
        self.preview_label.setText("框选预览")
        self.identify_btn.setEnabled(False)
        self.update_full_frame()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = self.full_frame_label.mapFromGlobal(self.mapToGlobal(event.pos()))
            if 0 <= pos.x() < self.scaled_w and 0 <= pos.y() < self.scaled_h:
                self.roi_start = (int(pos.x()), int(pos.y()))
                self.roi_end = None
                self.update_full_frame()

    def mouseMoveEvent(self, event):
        if self.roi_start:
            pos = self.full_frame_label.mapFromGlobal(self.mapToGlobal(event.pos()))
            x = max(0, min(int(pos.x()), self.scaled_w))
            y = max(0, min(int(pos.y()), self.scaled_h))
            self.roi_end = (x, y)
            self.update_full_frame()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.roi_start and self.roi_end:
            self.update_roi_preview()

    def on_confirm(self):
        self.final_text = self.result_edit.text().strip()
        if not re.match(TIME_PATTERN, self.final_text) and self.final_text not in ["", "无法识别，请手动输入"]:
            reply = QMessageBox.question(self, "格式校验", f"格式应为：YYYY-MM-DD HH:MM:SS.sss\n是否继续？",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return
        self.accept()