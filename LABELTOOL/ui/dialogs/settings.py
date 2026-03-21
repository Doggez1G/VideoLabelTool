"""
设置对话框模块（生产级）
========================
功能特性：
1. 滚动区域支持：防止设置项过多时界面溢出
2. 主题实时预览：切换主题后立即查看效果，取消则恢复
3. Tesseract路径选择：支持手动输入和文件浏览双模式
4. 路径标准化：自动处理 / 和 \\ 混用，统一为系统格式
5. 完备日志：记录用户操作和异常信息

技术细节：
- 使用QFormLayout保持标签右对齐
- 使用QScrollArea包装内容，支持垂直滚动
- normalize_path函数处理路径格式统一
"""

import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QSpinBox, QLineEdit, QComboBox,
    QDialogButtonBox, QLabel, QVBoxLayout, QWidget,
    QScrollArea, QFileDialog, QPushButton, QHBoxLayout,
    QMessageBox, QDoubleSpinBox
)
from PyQt6.QtCore import Qt

# 配置模块日志记录器
logger = logging.getLogger("SettingsDialog")


def normalize_path(path_str: str) -> str:
    """
    路径标准化函数

    处理逻辑：
    1. 去除首尾空白字符
    2. 将所有斜杠统一为正斜杠（/）处理
    3. 合并连续的多个斜杠为单个
    4. 使用pathlib转换为系统原生格式
    5. 展开用户目录符号~（Unix系统）

    Args:
        path_str: 原始路径字符串，可能包含混用的/和\
    Returns:
        标准化后的系统路径字符串
    """
    if not path_str:
        logger.debug("normalize_path: 输入为空字符串")
        return ""

    # 去除首尾空白
    path_str = path_str.strip()
    logger.debug(f"normalize_path: 输入 '{path_str}'")

    # 统一替换所有反斜杠为正斜杠（便于处理）
    normalized = path_str.replace("\\", "/")

    # 处理连续的 //（可能由替换产生或原路径就有）
    while "//" in normalized:
        normalized = normalized.replace("//", "/")

    # 使用Path对象处理为系统格式
    try:
        p = Path(normalized)
        # 展开用户目录（如 ~/.config → /home/user/.config）
        if "~" in str(p):
            p = p.expanduser()
            logger.debug(f"normalize_path: 展开用户目录 -> {p}")

        result = str(p)
        logger.debug(f"normalize_path: 输出 '{result}'")
        return result

    except Exception as e:
        logger.warning(f"normalize_path: 处理失败 [{e}]，返回原路径")
        return path_str


class SettingsDialog(QDialog):
    """
    应用程序设置对话框

    管理所有用户可配置项，包括播放器、主题、时间格式、OCR引擎等。
    支持主题实时预览和取消恢复机制。
    """

    def __init__(self, parent, current_config: dict, available_themes: list = None):
        """
        初始化设置对话框

        Args:
            parent: 父窗口，必须包含theme_manager属性用于主题切换
            current_config: 当前应用程序配置字典
            available_themes: 可用主题名称列表，默认为空列表
        """
        super().__init__(parent)
        self.parent_window = parent
        self.config = current_config
        self.available_themes = available_themes or []
        # 保存原始主题以便取消时恢复
        self.original_theme = current_config.get('theme', 'dark')

        # 初始化界面
        self._setup_window()
        self._setup_ui()

        logger.info(f"SettingsDialog初始化完成，当前主题: {self.original_theme}, "
                    f"可用主题数: {len(self.available_themes)}")

    def _setup_window(self):
        """配置对话框窗口基本属性"""
        self.setWindowTitle("设置")
        self.setModal(True)
        # 设置最小尺寸防止内容挤压，允许用户自由调整
        self.setMinimumSize(600, 400)
        self.resize(600, 500)
        logger.debug(f"窗口尺寸设置: 最小600x400, 当前600x500")

    def _setup_ui(self):
        """
        构建用户界面

        布局结构：
        QVBoxLayout -> QScrollArea -> QWidget -> QFormLayout -> 各设置组
        """
        # 主布局（全填充）
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 创建滚动区域（当内容超出窗口高度时可滚动）
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        # 隐藏水平滚动条，只允许垂直滚动
        logger.debug("滚动区域创建完成")

        # 内容容器
        content_widget = QWidget()
        content_widget.setObjectName("settingsContent")

        # 表单布局（标签右对齐，控件左对齐）
        form_layout = QFormLayout(content_widget)
        form_layout.setSpacing(16)
        form_layout.setContentsMargins(24, 24, 24, 24)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # 添加各设置组
        self._build_player_settings(form_layout)
        self._build_theme_settings(form_layout)
        self._build_time_settings(form_layout)
        self._build_ocr_settings(form_layout)
        self._build_buttons(form_layout)

        # 装配滚动区域
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

        logger.debug("UI构建完成")

    def _build_player_settings(self, layout: QFormLayout):
        """
        构建设置组：播放器选择

        Args:
            layout: 父级表单布局
        """
        layout.addRow(QLabel("<b>播放器设置</b>"))

        self.player_combo = QComboBox()
        self.player_combo.addItem("自定义播放器 (PyAV解码，支持更多格式)", "custom")
        self.player_combo.addItem("Qt 原生播放器 (系统解码，更稳定)", "qt")

        current_player = self.config.get('player_type', 'custom')
        index = self.player_combo.findData(current_player)
        if index >= 0:
            self.player_combo.setCurrentIndex(index)

        self.player_combo.setToolTip(
            "自定义播放器：使用PyAV库解码，支持更多视频格式，纯CPU解码\n"
            "Qt播放器：使用操作系统原生解码器，硬件加速，兼容性更好"
        )
        layout.addRow("视频播放器:", self.player_combo)
        logger.debug(f"播放器设置: 当前={current_player}")

    def _build_theme_settings(self, layout: QFormLayout):
        """
        构建设置组：界面主题

        Args:
            layout: 父级表单布局
        """
        layout.addRow(QLabel("<b>界面设置</b>"))

        self.theme_combo = QComboBox()
        # 动态加载可用主题
        if self.available_themes:
            for theme_name in self.available_themes:
                self.theme_combo.addItem(theme_name, theme_name)
            logger.debug(f"加载主题列表: {self.available_themes}")
        else:
            logger.warning("无可用主题列表")

        current_theme = self.config.get('theme', 'dark')
        index = self.theme_combo.findData(current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

        # 连接主题变更信号实现实时预览
        self.theme_combo.currentIndexChanged.connect(self._on_theme_preview)
        self.theme_combo.setToolTip("切换主题后立即预览效果，点击取消则不保存")
        layout.addRow("界面主题:", self.theme_combo)

    def _build_time_settings(self, layout: QFormLayout):
        """
        构建设置组：时间格式与播放控制

        Args:
            layout: 父级表单布局
        """
        layout.addRow(QLabel("<b>时间设置</b>"))

        # 时间粒度（对齐精度）
        self.gran_spin = QSpinBox()
        self.gran_spin.setRange(0, 86400000)  # 0到24小时
        self.gran_spin.setValue(self.config.get('granularity', 500))
        self.gran_spin.setSuffix(" ms")
        self.gran_spin.setToolTip("标注时间的对齐粒度，0表示精确到毫秒不对齐，500表示四舍五入到最近500ms")
        layout.addRow("时间粒度:", self.gran_spin)

        # 时间格式字符串
        self.format_edit = QLineEdit(self.config.get('time_format', "%Y-%m-%d %H:%M:%S.%f"))
        self.format_edit.setToolTip("Python strftime格式字符串，%Y年 %m月 %d日 %H时 %M分 %S秒 %f微秒")
        layout.addRow("时间格式:", self.format_edit)

        # 全局时间偏移（用于校准视频与真实时间）
        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(-86400000, 86400000)  # 支持正负24小时
        self.offset_spin.setValue(self.config.get('offset', 0))
        self.offset_spin.setSuffix(" ms")
        self.offset_spin.setToolTip("全局时间偏移量，用于校准视频时间戳与实际时间的偏差")
        layout.addRow("时间偏移:", self.offset_spin)

        # 快进/快退步长
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.1, 60.0)
        self.step_spin.setValue(self.config.get('step_seconds', 5.0))
        self.step_spin.setSingleStep(0.5)
        self.step_spin.setDecimals(1)
        self.step_spin.setSuffix(" 秒")
        self.step_spin.setToolTip("点击快进/快退按钮时跳跃的时间长度")
        layout.addRow("步长:", self.step_spin)

    def _build_ocr_settings(self, layout: QFormLayout):
        """
        构建设置组：OCR引擎与Tesseract路径

        特点：
        - 文本框和浏览按钮完全独立工作
        - 路径支持手动输入或文件选择
        - 自动路径标准化

        Args:
            layout: 父级表单布局
        """
        layout.addRow(QLabel("<b>OCR 设置</b>"))

        # OCR引擎选择下拉框
        self.ocr_combo = QComboBox()
        self.ocr_combo.addItem("EasyOCR (推荐，自动安装，开箱即用)", "EasyOCR")
        self.ocr_combo.addItem("Tesseract (需手动安装，可离线使用)", "Tesseract")

        current_ocr = self.config.get('ocr_engine', 'EasyOCR')
        index = self.ocr_combo.findData(current_ocr)
        if index >= 0:
            self.ocr_combo.setCurrentIndex(index)

        layout.addRow("OCR引擎:", self.ocr_combo)
        logger.debug(f"OCR设置: 当前={current_ocr}")

        # Tesseract路径选择容器（水平布局：输入框 + 浏览按钮）
        path_container = QWidget()
        path_layout = QHBoxLayout(path_container)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(8)

        # 路径输入框（始终可编辑，支持手动粘贴路径）
        self.tess_path_edit = QLineEdit()
        # 加载时标准化显示已有路径
        raw_path = self.config.get('tesseract_path', '')
        self.tess_path_edit.setText(normalize_path(raw_path))
        self.tess_path_edit.setPlaceholderText(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        self.tess_path_edit.setClearButtonEnabled(True)  # 启用右侧清除按钮
        self.tess_path_edit.setToolTip("可手动输入路径，或点击浏览选择；路径中的 / 和 \\ 会自动处理")

        # 浏览按钮（打开文件选择对话框）
        btn_browse = QPushButton("浏览...")
        btn_browse.setObjectName("secondaryBtn")
        btn_browse.setToolTip("打开文件浏览器选择tesseract.exe")
        btn_browse.clicked.connect(self._browse_tesseract)

        # 布局：输入框占主要空间（stretch=1），按钮固定宽度
        path_layout.addWidget(self.tess_path_edit, 1)
        path_layout.addWidget(btn_browse)

        layout.addRow("Tesseract路径:", path_container)


    def _build_buttons(self, layout: QFormLayout):
        """
        构建底部按钮（确定/取消）

        Args:
            layout: 父级表单布局
        """
        # 按钮组
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        # 添加空行作为间隔
        layout.addRow(QLabel(""))
        layout.addRow(btn_box)
        logger.debug("按钮组创建完成")

    def _on_ocr_changed(self, index: int):
        """
        OCR引擎变更回调

        Args:
            index: 当前选中的索引
        """
        current_data = self.ocr_combo.currentData()
        is_tesseract = (current_data == "Tesseract")

        # 根据选择启用/禁用路径编辑
        self.tess_path_edit.setEnabled(is_tesseract)
        # 查找浏览按钮（在布局中）并设置状态
        for i in range(self.tess_path_edit.parent().layout().count()):
            item = self.tess_path_edit.parent().layout().itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QPushButton):
                item.widget().setEnabled(is_tesseract)

        logger.info(f"OCR引擎切换为: {current_data}, Tesseract模式={is_tesseract}")

    def _update_ocr_ui_state(self):
        """根据当前OCR设置更新UI状态"""
        current = self.ocr_combo.currentData()
        is_tesseract = (current == "Tesseract")

        self.tess_path_edit.setEnabled(is_tesseract)

        # 查找并设置浏览按钮状态
        parent = self.tess_path_edit.parent()
        if parent:
            for i in range(parent.layout().count()):
                item = parent.layout().itemAt(i)
                if item and item.widget() and isinstance(item.widget(), QPushButton):
                    item.widget().setEnabled(is_tesseract)

        logger.debug(f"更新OCR UI状态: is_tesseract={is_tesseract}")

    def _browse_tesseract(self):
        """
        打开文件浏览器选择Tesseract可执行文件

        逻辑：
        1. 如果当前路径有效，打开其所在目录
        2. 否则尝试常见安装目录
        3. 选择后自动标准化路径并填入文本框
        """
        current_text = self.tess_path_edit.text().strip()

        # 确定初始目录
        initial_dir = ""
        if current_text:
            p = Path(current_text)
            if p.parent.exists():
                initial_dir = str(p.parent)
                logger.debug(f"使用当前路径目录: {initial_dir}")

        if not initial_dir:
            # 尝试常见安装路径
            common_paths = [
                r"C:\Program Files\Tesseract-OCR",
                r"C:\Program Files (x86)\Tesseract-OCR",
                str(Path.home() / "AppData" / "Local" / "Tesseract-OCR")
            ]
            for p in common_paths:
                if Path(p).exists():
                    initial_dir = p
                    logger.debug(f"使用常见路径: {initial_dir}")
                    break

        if not initial_dir:
            initial_dir = str(Path.home())

        # 打开文件对话框
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Tesseract-OCR 可执行文件",
            initial_dir,
            "可执行文件 (*.exe);;所有文件 (*)"
        )

        if path:
            # 标准化并填入路径
            normalized = normalize_path(path)
            self.tess_path_edit.setText(normalized)
            logger.info(f"用户选择Tesseract路径: {normalized}")

            # 验证文件名提示
            if "tesseract" not in Path(path).name.lower():
                QMessageBox.warning(
                    self,
                    "文件名提示",
                    f"选择的文件是 '{Path(path).name}'，可能不是Tesseract主程序。\n"
                    "建议选择名为 'tesseract.exe' 的文件。"
                )

    def _on_theme_preview(self, index: int):
        """
        主题实时预览回调

        切换主题时立即应用到主窗口，如果失败则回退。

        Args:
            index: 主题下拉框当前索引
        """
        selected_theme = self.theme_combo.itemData(index)
        if not selected_theme:
            logger.warning("主题预览: 无效选择")
            return

        if not hasattr(self.parent_window, 'theme_manager'):
            logger.error("主题预览: 父窗口无theme_manager")
            return

        logger.info(f"预览主题: {selected_theme}")
        success = self.parent_window.theme_manager.load_theme(selected_theme)

        if not success:
            logger.error(f"主题加载失败: {selected_theme}")
            QMessageBox.critical(
                self,
                "主题加载失败",
                f"无法加载主题 '{selected_theme}'，将恢复默认主题。"
            )
            # 恢复原始主题
            self.parent_window.theme_manager.load_theme(self.original_theme)
            # 重置下拉框到原始值
            orig_index = self.theme_combo.findData(self.original_theme)
            if orig_index >= 0:
                self.theme_combo.setCurrentIndex(orig_index)

    def get_values(self) -> dict:
        """
        获取当前所有设置值

        Returns:
            包含所有配置项的字典，路径已标准化
        """
        # 获取OCR引擎和路径
        ocr_engine = self.ocr_combo.currentData()
        tess_path = self.tess_path_edit.text().strip()
        tess_path = normalize_path(tess_path)

        # 如果使用Tesseract，标准化路径
        if ocr_engine == "Tesseract" :
            if tess_path and not Path(tess_path).exists():
                logger.warning(f'tesseract_path不存在')

        values = {
            'granularity': self.gran_spin.value(),
            'time_format': self.format_edit.text(),
            'offset': self.offset_spin.value(),
            'ocr_engine': ocr_engine,
            'tesseract_path': tess_path,
            'theme': self.theme_combo.currentData(),
            'step_seconds': self.step_spin.value(),
            'player_type': self.player_combo.currentData()
        }

        logger.info(f"获取设置值: {values}")
        return values

    def reject(self):
        """
        用户取消设置

        恢复原始主题设置，确保预览的变更不会保留。
        """
        if hasattr(self.parent_window, 'theme_manager'):
            current = self.theme_combo.currentData()
            if current != self.original_theme:
                logger.info(f"取消设置，恢复原始主题: {self.original_theme}")
                self.parent_window.theme_manager.load_theme(self.original_theme)

        logger.info("用户取消设置")
        super().reject()

    def accept(self):
        """
        用户确认保存设置

        进行简单验证，确认后关闭对话框。
        """
        # 验证Tesseract路径（如果使用Tesseract）
        if self.ocr_combo.currentData() == "Tesseract":
            path = self.tess_path_edit.text().strip()
            if path and not Path(path).exists():
                reply = QMessageBox.question(
                    self,
                    "路径不存在",
                    f"指定的Tesseract路径不存在:\n{path}\n\n是否仍要保存？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    logger.info("用户因路径无效取消保存")
                    return

        logger.info("用户确认保存设置")
        super().accept()