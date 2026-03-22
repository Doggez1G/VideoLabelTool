# ================== 必须放在最前面的导入 (解决DLL冲突) ==================
import os
import sys

# 1. 修复 OpenMP 库冲突
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'

# 2. 添加 PyTorch DLL 加载修复
os.environ['TORCH_CUDNN_V8_API_DISABLED'] = '1'  # 禁用 CUDNN V8 API


# 3. 导入 torch 并添加错误处理

import torch


# =========================================================================

# 导入 PyQt6 和主窗口
from PyQt6.QtWidgets import QApplication
from utils.logger import setup_logging, get_logger
from ui.main_window import MainWindow


def main():
    # 初始化日志系统（必须最先执行）
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    setup_logging(log_dir=log_dir, level="DEBUG")
    logger = get_logger("Main")

    logger.info("=" * 60)
    logger.info("录屏卡顿标注工具 Pro 启动")
    logger.info("=" * 60)

    app = QApplication(sys.argv)
    app.setApplicationName("录屏卡顿标注工具 Pro")

    window = MainWindow()
    window.show()

    exit_code = app.exec()
    logger.info(f"程序退出，退出码: {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()