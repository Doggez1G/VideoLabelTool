"""
主窗口
======
- 左侧: 视频播放区（支持自定义/Qt 两种播放器切换）
- 右侧: 数据管理区（标注记录表格 + 配置信息）

"""

from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

from utils.logger import get_logger
from utils.config import load_config, save_config
from utils.time import ms_to_hms
from ui.themes.theme_manager import ThemeManager
from ui.dialogs.settings import SettingsDialog
from videocore.frame_renderer import FrameRenderer
from videocore.i_player import IPlayer
from videocore.qt_player import QtPlayer
from videocore.custom_player import CustomPlayer

logger = get_logger("MainWindow")


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("录屏卡顿标注工具 Pro")
        self.resize(1400, 900)
        self.setMinimumSize(1200, 800)

        # 加载配置
        self.config = load_config()
        self._apply_config()

        # 播放器和渲染器
        self.player: Optional[IPlayer] = None
        self.renderer = FrameRenderer()

        # 状态变量（增加详细注释）
        self.video_path: Optional[str] = None  # 当前视频文件路径
        self.is_seeking: bool = False  # 是否正在拖动进度条（避免冲突）
        self.is_playing: bool = False  # 当前播放状态缓存
        self.video_start_time_str: str = ""  # 视频起始绝对时间（用于时间戳计算）
        self.imported_first_time_str: str = ""  # 导入标签的起始时间
        self.records: list = []  # 标注记录列表
        self.current_selected_row: int = -1  # 表格当前选中行
        self.current_selected_col: int = -1  # 表格当前选中列
        self.current_video_ms: int = 0  # 当前视频位置（毫秒）
        self._was_playing_before_seek: bool = False  # 拖动前是否正在播放（用于恢复）

        self._init_ui()
        self._create_menu_bar()
        self.update_button_states()
        self.update_config_display()

        logger.info("主窗口初始化完成")

    # ==================== 配置管理 ====================

    def _apply_config(self):
        """从配置字典中提取设置项到实例变量"""
        self.settings_theme = self.config.get("theme", "dark")
        self.settings_granularity_ms = self.config.get("granularity", 500)
        self.settings_time_format = self.config.get("time_format", "%Y-%m-%d %H:%M:%S.%f")
        self.settings_time_offset_ms = self.config.get("offset", 0)
        self.settings_step_seconds = self.config.get("step_seconds", 5.0)
        self.settings_player_type = self.config.get("player_type", "custom")
        logger.debug(f"配置已应用: 播放器={self.settings_player_type}, 主题={self.settings_theme}")

    def _reset_state(self):
        """
        重置应用状态（用于重新加载视频时）
        关键修复：确保重新选择文件时所有状态正确重置
        """
        logger.info("重置应用状态")
        self.video_path = None
        self.is_playing = False
        self.is_seeking = False
        self.video_start_time_str = ""
        self.imported_first_time_str = ""
        self.records = []
        self.current_selected_row = -1
        self.current_selected_col = -1
        self.current_video_ms = 0
        self._was_playing_before_seek = False

        # 重置UI状态（播放按钮文字等）
        self.btn_play.setText("▶ 播放")
        self.slider.setValue(0)
        self._update_time_display(0, 0)

        # 清空表格
        self.table.setRowCount(0)

    # ==================== UI 构建 ====================

    def _init_ui(self):
        """初始化界面布局"""
        # 加载主题
        project_root = Path(__file__).parent.parent
        themes_dir = project_root / "ui" / "themes"
        self.theme_manager = ThemeManager(themes_dir=str(themes_dir))
        self.theme_manager.load_theme(self.settings_theme)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 分割器：左右面板
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)
        splitter.setStretchFactor(0, 3)  # 左侧视频区占3份
        splitter.setStretchFactor(1, 1)  # 右侧数据区占1份

        # ---- 左侧：视频播放区 ----
        left_widget = self._build_video_panel()
        # ---- 右侧：数据管理区 ----
        right_widget = self._build_data_panel()

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)

        # 设置初始分割比例
        splitter.setSizes([1000, 400])

        main_layout.addWidget(splitter)

    def _build_video_panel(self) -> QWidget:
        """
        构建左侧视频播放面板
        包含：视频显示区、进度条、播放控制、标注控制
        """
        widget = QWidget()
        widget.setObjectName("videoPanel")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 1. 视频显示区域（StackedWidget 切换两种播放器的显示方式）
        self.video_stack = QStackedWidget()
        self.video_stack.setObjectName("videoStack")

        # Custom Player 用 QLabel 显示
        self.video_label_custom = QLabel("请通过菜单【文件 → 打开视频文件】加载视频")
        self.video_label_custom.setObjectName("VideoLabel")
        self.video_label_custom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label_custom.setMinimumSize(640, 480)
        # 启用鼠标跟踪以支持未来的交互功能（如ROI选择）
        self.video_label_custom.setMouseTracking(True)

        # Qt Player 用 QVideoWidget（通过 container 包装）
        self.video_container_qt = QWidget()
        self.video_container_qt.setObjectName("qtVideoContainer")
        qt_layout = QVBoxLayout(self.video_container_qt)
        qt_layout.setContentsMargins(0, 0, 0, 0)

        self.video_stack.addWidget(self.video_label_custom)
        self.video_stack.addWidget(self.video_container_qt)

        layout.addWidget(self.video_stack, stretch=1)

        # 2. 进度条
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setEnabled(False)
        self.slider.setMinimumHeight(30)
        self.slider.setObjectName("videoSlider")

        # 进度条信号连接：按下暂停、移动时预览、释放后跳转
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)
        layout.addWidget(self.slider)

        # 3. 控制按钮
        ctrl_container = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_container)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(12)

        # 第一行：播放控制（后退、播放/暂停、前进、时间显示）
        play_row = QWidget()
        play_layout = QHBoxLayout(play_row)
        play_layout.setContentsMargins(0, 0, 0, 0)
        play_layout.setSpacing(12)

        self.btn_rewind = QPushButton("⏪ 后退")
        self.btn_rewind.setObjectName("controlBtn")
        self.btn_rewind.setToolTip(f"后退 {self.settings_step_seconds} 秒")
        self.btn_rewind.clicked.connect(self._step_backward)

        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setObjectName("PrimaryBtn")
        self.btn_play.setMinimumWidth(120)
        self.btn_play.setToolTip("播放/暂停 (空格键)")
        self.btn_play.clicked.connect(self._toggle_play)

        self.btn_forward = QPushButton("快进 ⏩")
        self.btn_forward.setObjectName("controlBtn")
        self.btn_forward.setToolTip(f"前进 {self.settings_step_seconds} 秒")
        self.btn_forward.clicked.connect(self._step_forward)

        self.lbl_time = QLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_time.setObjectName("timeLabel")
        self.lbl_time.setMinimumWidth(220)
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 在时间标签旁边添加音量控制
        volume_container = QWidget()
        volume_layout = QHBoxLayout(volume_container)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(8)

        # 音量图标（可点击静音）
        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setObjectName("muteBtn")
        self.btn_mute.setFixedSize(32, 32)
        self.btn_mute.setToolTip("静音/取消静音")
        self.btn_mute.clicked.connect(self._toggle_mute)

        # 音量滑块（0-100）
        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(100)
        self.slider_volume.setFixedWidth(100)
        self.slider_volume.setObjectName("volumeSlider")
        self.slider_volume.setToolTip("音量调节")
        self.slider_volume.valueChanged.connect(self._on_volume_changed)

        volume_layout.addWidget(self.btn_mute)
        volume_layout.addWidget(self.slider_volume)

        play_layout.addWidget(self.btn_rewind)
        play_layout.addWidget(self.btn_play)
        play_layout.addWidget(self.btn_forward)
        play_layout.addStretch()
        play_layout.addWidget(self.lbl_time)
        play_layout.addSpacing(20)
        play_layout.addWidget(volume_container)  # 添加在这里
        play_layout.addStretch()

        ## 第二行：标注控制（OCR、标记开始、标记结束）
        mark_row = QWidget()
        mark_layout = QHBoxLayout(mark_row)
        mark_layout.setContentsMargins(0, 0, 0, 0)
        mark_layout.setSpacing(8)

        self.btn_ocr = QPushButton("🔍 识别首帧时钟")
        self.btn_ocr.setObjectName("PrimaryBtn")

        self.btn_mark_start = QPushButton("🔴 标记卡顿开始")
        self.btn_mark_start.setObjectName("WarningBtn")

        self.btn_mark_end = QPushButton("🟢 标记卡顿结束")
        self.btn_mark_end.setObjectName("SuccessBtn")

        mark_layout.addWidget(self.btn_ocr)
        mark_layout.addWidget(self.btn_mark_start)
        mark_layout.addWidget(self.btn_mark_end)
        mark_layout.addStretch()

        ctrl_layout.addWidget(play_row)
        ctrl_layout.addWidget(mark_row)
        layout.addWidget(ctrl_container)

        return widget

    def _build_data_panel(self) -> QWidget:
        """
        构建右侧数据管理面板
        包含：操作按钮、标注记录表格、配置信息显示
        """
        widget = QWidget()
        widget.setObjectName("dataPanel")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # 1. 操作按钮组
        btn_group = QWidget()
        btn_layout = QVBoxLayout(btn_group)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(10)

        edit_row = QWidget()
        edit_layout = QHBoxLayout(edit_row)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(8)

        self.btn_edit_start = QPushButton("✏️ 编辑开始时间")
        self.btn_edit_start.setObjectName("secondaryBtn")
        self.btn_edit_end = QPushButton("✏️ 编辑结束时间")
        self.btn_edit_end.setObjectName("secondaryBtn")
        edit_layout.addWidget(self.btn_edit_start)
        edit_layout.addWidget(self.btn_edit_end)
        edit_layout.addStretch()

        data_row = QWidget()
        data_layout = QHBoxLayout(data_row)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(8)

        self.btn_del = QPushButton("🗑️ 删除记录")
        self.btn_del.setObjectName("dangerBtn")
        self.btn_add = QPushButton("➕ 新增手动记录")
        self.btn_add.setObjectName("primaryBtn")
        data_layout.addWidget(self.btn_del)
        data_layout.addWidget(self.btn_add)
        data_layout.addStretch()

        btn_layout.addWidget(edit_row)
        btn_layout.addWidget(data_row)
        layout.addWidget(btn_group)

        # 2. 标注记录表格
        table_header = QLabel("📋 标注记录列表")
        table_header.setObjectName("sectionHeader")
        layout.addWidget(table_header)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["开始时间", "结束时间", "标签"])
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(300)
        layout.addWidget(self.table, stretch=1)

        # 3. 配置信息展示
        config_group = QGroupBox("⚙️ 当前配置信息")
        config_group.setObjectName("configGroup")
        config_layout = QFormLayout(config_group)
        config_layout.setContentsMargins(16, 20, 16, 16)
        config_layout.setSpacing(12)
        config_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_video_start = QLabel("未设置")
        self.lbl_video_start.setObjectName("configValue")

        self.lbl_imported_start = QLabel("未导入")
        self.lbl_imported_start.setObjectName("configValue")

        self.lbl_granularity = QLabel("500 ms")
        self.lbl_granularity.setObjectName("configValue")

        self.lbl_save_format = QLabel("%Y-%m-%d %H:%M:%S.%f")
        self.lbl_save_format.setObjectName("configValue")

        self.lbl_offset = QLabel("0 ms")
        self.lbl_offset.setObjectName("configValue")

        self.lbl_player_type = QLabel("自定义")
        self.lbl_player_type.setObjectName("configValue")

        config_layout.addRow("视频开始时间:", self.lbl_video_start)
        config_layout.addRow("导入标签开始时间:", self.lbl_imported_start)
        config_layout.addRow("时间粒度:", self.lbl_granularity)
        config_layout.addRow("保存时间格式:", self.lbl_save_format)
        config_layout.addRow("全局时间偏移:", self.lbl_offset)
        config_layout.addRow("当前播放器:", self.lbl_player_type)
        layout.addWidget(config_group)

        return widget

    # ==================== 菜单栏 ====================

    def _create_menu_bar(self):
        """创建应用菜单栏"""
        menubar = self.menuBar()
        menubar.setObjectName("menuBar")

        # 文件菜单
        file_menu = menubar.addMenu("📁 文件")
        file_menu.setObjectName("menu")

        self.action_open = QAction("打开视频文件...", self)
        self.action_open.setShortcut("Ctrl+O")
        self.action_open.setStatusTip("打开视频文件进行标注")
        self.action_open.triggered.connect(self._select_video)
        file_menu.addAction(self.action_open)

        file_menu.addSeparator()

        self.action_save = QAction("💾 保存标签", self)
        self.action_save.setShortcut("Ctrl+S")
        self.action_save.setEnabled(False)
        self.action_save.triggered.connect(self._save_labels)
        file_menu.addAction(self.action_save)

        self.action_import = QAction("📥 导入标签", self)
        self.action_import.setShortcut("Ctrl+I")
        self.action_import.setEnabled(False)
        self.action_import.triggered.connect(self._import_labels)
        file_menu.addAction(self.action_import)

        file_menu.addSeparator()

        action_exit = QAction("退出", self)
        action_exit.setShortcut("Alt+F4")
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

        # 设置菜单
        settings_menu = menubar.addMenu("⚙️ 设置")

        self.action_settings = QAction("首选项...", self)
        self.action_settings.setShortcut("Ctrl+,")
        self.action_settings.triggered.connect(self._open_settings)
        settings_menu.addAction(self.action_settings)

        # 帮助菜单
        help_menu = menubar.addMenu("❓ 帮助")

        action_about = QAction("关于", self)
        action_about.triggered.connect(self._show_about)
        help_menu.addAction(action_about)

        logger.debug("菜单栏创建完成")

    # ==================== 状态更新 ====================

    def update_config_display(self):
        """更新配置信息显示"""
        self.lbl_video_start.setText(
            self.video_start_time_str if self.video_start_time_str else "未设置"
        )
        self.lbl_imported_start.setText(
            self.imported_first_time_str if self.imported_first_time_str else "未导入"
        )
        self.lbl_granularity.setText(f"{self.settings_granularity_ms} ms")
        self.lbl_save_format.setText(self.settings_time_format)
        self.lbl_offset.setText(f"{self.settings_time_offset_ms} ms")
        p_str = "自定义" if self.settings_player_type == "custom" else "Qt 原生"
        self.lbl_player_type.setText(p_str)
        logger.debug("配置显示已更新")

    def update_button_states(self):
        """
        根据当前应用状态更新各按钮的可用性
        规则：
        - 基础控制（播放/前进/后退）：需要加载视频
        - 标记功能：需要设置视频起始时间
        - 标记结束：需要有待结束的标记（未闭合的开始）
        """
        has_video = bool(self.video_path)
        has_start_time = bool(self.video_start_time_str)
        has_pending = bool(self.records) and self.records[-1].get("end_raw") is None

        # 文件菜单
        self.action_save.setEnabled(has_video and has_start_time and bool(self.records))
        self.action_import.setEnabled(has_video)

        # 播放控制
        self.btn_play.setEnabled(has_video)
        self.btn_rewind.setEnabled(has_video)
        self.btn_forward.setEnabled(has_video)
        self.slider.setEnabled(has_video)

        # 标注控制
        self.btn_ocr.setEnabled(has_video)
        self.btn_mark_start.setEnabled(has_video and has_start_time and not has_pending)
        self.btn_mark_end.setEnabled(has_video and has_start_time and has_pending)
        self.btn_add.setEnabled(has_video and has_start_time)

        logger.debug(f"按钮状态更新: has_video={has_video}, has_start={has_start_time}, pending={has_pending}")

    # ==================== 设置对话框 ====================

    def _open_settings(self):
        """打开设置对话框"""
        available_themes = self.theme_manager.get_available_themes()
        dialog = SettingsDialog(self, self.config, available_themes)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_config = dialog.get_values()
            old_config = self.config.copy()
            # 更新配置
            self.config.update(new_config)
            self._apply_config()
            save_config(self.config)

            self.update_config_display()


            # 立即应用步长等无需重启的设置
            self.btn_rewind.setToolTip(f"后退 {self.settings_step_seconds} 秒")
            self.btn_forward.setToolTip(f"前进 {self.settings_step_seconds} 秒")
            logger.info(f"旧设置记录: {old_config}")
            logger.info(f"新设置已更新并保存: {new_config}")

    def _show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于 录屏卡顿标注工具",
            "<h2>录屏卡顿标注工具 Pro</h2>"
            "<p>版本: 2.0</p>"
            "<p>一个专业的视频时间戳标注工具，支持自定义和Qt原生两种播放引擎。</p>"
            "<p>支持功能：</p>"
            "<ul>"
            "<li>高精度视频播放控制</li>"
            "<li>音视频同步播放</li>"
            "<li>OCR时间戳识别</li>"
            "<li>卡顿时间段标记</li>"
            "</ul>"
        )

    # ==================== 播放器核心逻辑 ====================

    def _select_video(self):
        """
        选择并加载视频文件
        关键修复：先重置状态再加载新视频，避免按钮状态混乱
        """

        # 打开文件对话框
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", "",
            "视频文件 (*.mp4 *.avi *.mkv *.mov *.flv *.wmv);;所有文件 (*)"
        )
        if not path:
            logger.debug("用户取消文件选择")
            return

            # 如果已有视频在播放，先执行完整清理流程
        if self.player is not None or self.video_path is not None:
            logger.info("重新选择视频：执行完整清理流程...")
            self._reset_state()
            self._cleanup_player()

            # 【关键】给Qt时间完成对象删除（100ms延迟）
            # 原因：deleteLater()是异步的，需要事件循环执行
            # 如果不等待，新创建的QVideoWidget可能与旧的资源冲突
            QApplication.processEvents()
            import time
            time.sleep(0.1)  # 100ms延迟，确保对象已实际删除
            QApplication.processEvents()
            logger.debug("清理后的延迟等待完成")

        logger.info(f"用户选择视频文件: {path}")
        self.video_path = path
        # 初始化播放器（根据配置创建对应类型
        self._init_player()
        # 加载视频
        if self.player.load(path):
            self._setup_video_widget()
            self.update_button_states()
            logger.info("视频加载流程完成")
        else:
            QMessageBox.critical(self, "错误", "无法加载视频文件")
            logger.error(f"视频加载失败: {path}")
            self.video_path = None

    def _cleanup_player(self):
        """清理现有播放器资源"""
        if self.player is None:
            logger.debug("清理播放器：当前无播放器实例")
            return

        logger.info("开始清理播放器资源...")

        # 步骤1：停止播放（忽略可能的异常）
        try:
            self.player.stop()
            logger.debug("播放器已停止")
        except Exception as e:
            logger.warning(f"停止播放器时出错（可忽略）: {e}")

        # 步骤2：强制处理Qt事件队列
        # 原因：确保上面的stop()命令已经被Qt处理，特别是QMediaPlayer的异步操作
        QApplication.processEvents()
        logger.debug("Qt事件队列已处理")

        # 步骤3：断开所有信号连接（防止信号发送到即将删除的对象）
        signals = [
            'sig_frame_ready', 'sig_position_changed',
            'sig_duration_changed', 'sig_state_changed',
            'sig_finished', 'sig_error'
        ]

        disconnected_count = 0
        for signal_name in signals:
            try:
                if hasattr(self.player, signal_name):
                    signal = getattr(self.player, signal_name)
                    signal.disconnect()
                    disconnected_count += 1
            except (TypeError, RuntimeError):
                # TypeError: 信号未连接
                # RuntimeError: 信号已断开
                pass

        logger.debug(f"断开了 {disconnected_count} 个信号连接")

        # 步骤4：根据播放器类型执行特定清理
        if isinstance(self.player, QtPlayer):
            logger.debug("检测到QtPlayer，执行特殊清理流程...")
            try:
                # 获取VideoWidget并从StackedWidget移除
                qt_widget = self.player.get_video_widget()
                if qt_widget:
                    index = self.video_stack.indexOf(qt_widget)
                    if index >= 0:
                        self.video_stack.removeWidget(qt_widget)
                        logger.debug(f"从StackedWidget移除VideoWidget（索引{index}）")

                    # 调用QtPlayer的特殊清理方法（内部会处理延迟删除）
                    self.player.release_resources()
                    logger.debug("QtPlayer.release_resources()已调用")
            except Exception as e:
                logger.error(f"清理QtPlayer Widget失败: {e}")

        elif isinstance(self.player, CustomPlayer):
            logger.debug("检测到CustomPlayer，确保线程已停止...")
            try:
                # CustomPlayer的stop()已经处理了线程停止
                # 这里额外确保一下（重复stop是安全的）
                self.player.stop()
            except Exception as e:
                logger.error(f"清理CustomPlayer失败: {e}")

        # 步骤5：删除播放器对象（延迟删除更安全）
        # deleteLater()会将删除操作加入Qt事件队列，而不是立即执行
        try:
            self.player.deleteLater()
            logger.debug("已标记播放器对象延迟删除")
        except Exception as e:
            logger.warning(f"标记删除播放器时异常: {e}")

        self.player = None

        # 步骤6：再次处理事件，确保删除操作已入队
        QApplication.processEvents()

        logger.info("播放器资源清理流程完成")

    def _init_player(self):
        """
        初始化播放器实例
        根据配置创建自定义播放器或Qt原生播放器
        """
        player_type = self.settings_player_type

        if player_type == "qt":
            self.player = QtPlayer(self)
            logger.info("创建Qt原生播放器实例")
        else:
            self.player = CustomPlayer(self)
            logger.info("创建自定义播放器(PyAV)实例")

        # 连接播放器信号到UI更新槽
        self.player.sig_frame_ready.connect(self._on_frame_ready)
        self.player.sig_position_changed.connect(self._on_position_changed)
        self.player.sig_duration_changed.connect(self._on_duration_changed)
        self.player.sig_state_changed.connect(self._on_state_changed)
        self.player.sig_finished.connect(self._on_finished)
        self.player.sig_error.connect(self._on_player_error)

    def _setup_video_widget(self):
        """修复：根据播放器类型安全设置视频组件"""
        logger.debug(f"设置视频组件，播放器类型: {self.settings_player_type}")

        # 先切换到自定义Label（索引0），这是安全的默认状态
        self.video_stack.setCurrentIndex(0)
        QApplication.processEvents()  # 确保切换完成
        logger.debug("已切换到安全页面（索引0）")

        if self.settings_player_type == "qt":
            # Qt播放器模式
            logger.debug("配置QtPlayer视频组件...")

            # 移除旧的Qt Widget（如果存在）
            old_widget = self.video_stack.widget(1)
            if old_widget:
                self.video_stack.removeWidget(old_widget)
                # 不立即deleteLater，让release_resources处理或Python GC
                logger.debug("移除了旧的Qt视频组件")
                QApplication.processEvents()

            # 获取新的VideoWidget并添加到StackedWidget
            qt_video_widget = self.player.get_video_widget()
            if qt_video_widget:
                self.video_stack.addWidget(qt_video_widget)
                self.video_stack.setCurrentIndex(1)  # 切换到视频页面
                logger.debug("已添加并切换到Qt视频组件（索引1）")
        else:
            # 自定义播放器模式（使用Label显示）
            logger.debug("配置CustomPlayer视频组件（使用Label）")
            self.video_stack.setCurrentIndex(0)

    def _toggle_play(self):
        """切换播放/暂停状态"""
        if not self.player:
            logger.warning("播放按钮点击但播放器未初始化")
            return

        if self.player.is_playing():
            self.player.pause()
            logger.debug("用户操作: 暂停")
        else:
            self.player.play()
            logger.debug("用户操作: 播放")

    def _step_forward(self):
        """前进指定秒数（默认5秒）"""
        if not self.player:
            return

        current_pos = self.player.get_position()
        step_ms = int(self.settings_step_seconds * 1000)
        new_pos = current_pos + step_ms

        logger.debug(f"前进操作: {current_pos}ms -> {new_pos}ms")
        self.player.seek(new_pos)

    def _step_backward(self):
        """后退指定秒数（默认5秒）"""
        if not self.player:
            return

        current_pos = self.player.get_position()
        step_ms = int(self.settings_step_seconds * 1000)
        new_pos = max(0, current_pos - step_ms)

        logger.debug(f"后退操作: {current_pos}ms -> {new_pos}ms")
        self.player.seek(new_pos)

    def _on_volume_changed(self, value):
        """音量变化回调"""
        volume = value / 100.0
        if self.player:
            # 根据播放器类型设置音量
            if isinstance(self.player, QtPlayer):
                self.player.set_volume(volume)
            elif hasattr(self.player, 'set_volume'):
                self.player.set_volume(volume)

        # 更新图标
        if value == 0:
            self.btn_mute.setText("🔇")
        elif value < 50:
            self.btn_mute.setText("🔉")
        else:
            self.btn_mute.setText("🔊")

        logger.debug(f"音量调节: {value}%")

    def _toggle_mute(self):
        """静音切换"""
        current = self.slider_volume.value()
        if current > 0:
            self._last_volume = current
            self.slider_volume.setValue(0)
        else:
            self.slider_volume.setValue(self._last_volume if hasattr(self, '_last_volume') else 100)

    # ==================== 进度条逻辑（修复版） ====================

    def _on_slider_pressed(self):
        """用户按下进度条：暂停播放以便精确定位"""
        if not self.player:
            return

        self.is_seeking = True
        self._was_playing_before_seek = self.player.is_playing()

        if self._was_playing_before_seek:
            self.player.pause()
            logger.debug("进度条按下：暂停播放")

    def _on_slider_moved(self, value: int):
        """
        用户拖动进度条：实时更新显示（但不实际跳转，避免卡顿）
        value: 0-1000的滑块位置
        """
        if not self.player:
            return

        duration = self.player.get_duration()
        if duration == 0:
            return

        # 计算目标时间并更新显示
        target_ms = int(value / 1000.0 * duration)
        self._update_time_display(target_ms, duration)

        # 可选：实时预览（如果性能允许）
        # self.player.seek(target_ms)

    def _on_slider_released(self):
        """用户释放进度条：执行实际的seek操作"""
        if not self.player:
            return

        self.is_seeking = False
        duration = self.player.get_duration()
        value = self.slider.value()
        target_ms = int(value / 1000.0 * duration)

        logger.debug(f"进度条释放：Seek到 {target_ms}ms")
        self.player.seek(target_ms)

        # 恢复之前的播放状态
        if self._was_playing_before_seek:
            self.player.play()
            logger.debug("恢复播放状态")

    # ==================== 播放器回调 ====================

    def _on_frame_ready(self, qimage):
        """
        自定义播放器收到新帧：渲染到Label上
        qimage: PyQt6.QtGui.QImage
        """
        if self.settings_player_type != "custom":
            return

        pixmap = self.renderer.render(qimage, self.video_label_custom.size())
        self.video_label_custom.setPixmap(pixmap)

    def _on_position_changed(self, ms: int):
        """
        播放位置变化回调
        更新进度条和时间显示（但不在拖动时更新进度条，避免冲突）
        """
        self.current_video_ms = ms

        # 更新进度条（如果不是用户正在拖动）
        if not self.is_seeking and self.player:
            duration = self.player.get_duration()
            if duration > 0:
                # blockSignals防止触发sliderMoved
                self.slider.blockSignals(True)
                slider_val = int(ms / duration * 1000)
                self.slider.setValue(slider_val)
                self.slider.blockSignals(False)

        self._update_time_display(ms, self.player.get_duration() if self.player else 0)

    def _on_duration_changed(self, ms: int):
        """视频时长确定回调（加载完成后）"""
        logger.info(f"视频时长确定: {ms}ms ({ms / 1000:.2f}s)")
        self.slider.setRange(0, 1000)
        current = self.player.get_position() if self.player else 0
        self._update_time_display(current, ms)

    def _on_state_changed(self, is_playing: bool):
        """
        播放状态变化回调
        关键修复：确保按钮文字和内部状态一致
        """
        self.is_playing = is_playing

        if is_playing:
            self.btn_play.setText("⏸ 暂停")
            self.btn_play.setToolTip("暂停播放")
            logger.info("播放状态变更为：播放中")
        else:
            self.btn_play.setText("▶ 播放")
            self.btn_play.setToolTip("开始播放")
            logger.info("播放状态变更为：已暂停")

    def _on_finished(self):
        """播放自然结束（到达视频结尾）"""
        logger.info("视频播放自然结束")
        self.btn_play.setText("▶ 播放")
        self.is_playing = False
        # 确保进度条在结尾
        self.slider.setValue(1000)

    def _on_player_error(self, error_msg: str):
        """播放器错误处理"""
        logger.error(f"播放器错误: {error_msg}")
        QMessageBox.warning(self, "播放器错误", f"播放过程中发生错误：\n{error_msg}")
        self.update_button_states()

    def _update_time_display(self, current_ms: int, total_ms: int):
        """更新时间标签显示（格式：当前时间 / 总时长）"""
        current_str = ms_to_hms(current_ms)
        total_str = ms_to_hms(total_ms)
        self.lbl_time.setText(f"{current_str} / {total_str}")

    # ==================== 标注功能（占位，供后续实现） ====================

    def _save_labels(self):
        """保存标注到文件"""
        logger.info("保存标签功能触发")
        # TODO: 实现保存逻辑

    def _import_labels(self):
        """从文件导入标注"""
        logger.info("导入标签功能触发")
        # TODO: 实现导入逻辑

    def closeEvent(self, event):
        """窗口关闭事件：清理资源"""
        logger.info("应用程序关闭，清理资源")
        self._cleanup_player()
        event.accept()
