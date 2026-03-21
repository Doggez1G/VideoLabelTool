"""
主题管理器
==========
负责主题的加载、切换和管理
支持热切换（无需重启应用）
"""

from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QFile, QTextStream

from utils.logger import get_logger

logger = get_logger("ThemeManager")


class ThemeManager:
    """主题管理器类"""

    def __init__(self, themes_dir: str = "themes"):
        """
        初始化主题管理器

        Args:
            themes_dir: 主题文件存放目录路径
        """
        self.themes_dir = Path(themes_dir)
        self._available_themes = {}
        self._current_theme = "dark"

        # 扫描可用主题
        self._scan_themes()
        logger.info(f"主题管理器初始化，发现 {len(self._available_themes)} 个主题")

    def _scan_themes(self) -> dict:
        """
        扫描主题目录下的所有.qss文件

        Returns:
            主题名到文件路径的映射字典
        """
        self._available_themes = {}

        if not self.themes_dir.exists():
            logger.warning(f"主题目录不存在: {self.themes_dir}")
            return self._available_themes

        for qss_file in self.themes_dir.glob("*.qss"):
            theme_name = qss_file.stem
            self._available_themes[theme_name] = qss_file
            logger.debug(f"发现主题: {theme_name} -> {qss_file}")

        return self._available_themes

    def get_available_themes(self) -> list:
        """
        获取所有可用主题名称列表

        Returns:
            主题名称字符串列表
        """
        return list(self._available_themes.keys())

    def get_current_theme(self) -> str:
        """获取当前主题名称"""
        return self._current_theme

    def load_theme(self, theme_name: str) -> bool:
        """
        加载并应用指定主题

        Args:
            theme_name: 主题名称（对应.qss文件名，不含扩展名）

        Returns:
            加载成功返回True，失败返回False
        """
        # 检查主题是否存在
        if theme_name not in self._available_themes:
            logger.error(f"主题 '{theme_name}' 不存在，可用主题: {list(self._available_themes.keys())}")
            # 尝试使用默认主题
            if theme_name != "dark" and "dark" in self._available_themes:
                logger.info("尝试回退到默认主题 'dark'")
                theme_name = "dark"
            else:
                return False

        qss_file = self._available_themes[theme_name]

        try:
            # 读取QSS文件内容
            with open(qss_file, "r", encoding="utf-8") as f:
                stylesheet = f.read()

            if not stylesheet.strip():
                logger.warning(f"主题文件为空: {qss_file}")
                return False

            # 获取应用实例并应用样式
            app = QApplication.instance()
            if app:
                # 先清空当前样式（避免样式叠加冲突）
                app.setStyleSheet("")
                # 强制处理事件，确保样式清除生效
                app.processEvents()

                # 应用新样式
                app.setStyleSheet(stylesheet)
                # 再次处理事件确保应用
                app.processEvents()

                self._current_theme = theme_name
                logger.info(f"主题 '{theme_name}' 加载成功")
                return True
            else:
                logger.error("无法获取QApplication实例")
                return False

        except Exception as e:
            logger.error(f"加载主题 '{theme_name}' 失败: {e}")
            return False

    def reload_current_theme(self) -> bool:
        """
        重新加载当前主题（用于主题文件修改后的热重载）

        Returns:
            重载成功返回True
        """
        return self.load_theme(self._current_theme)

    def apply_default_theme(self) -> bool:
        """
        应用默认主题（dark）

        Returns:
            应用成功返回True
        """
        return self.load_theme("dark")