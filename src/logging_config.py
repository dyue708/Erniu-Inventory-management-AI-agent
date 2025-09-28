"""
统一日志配置模块
"""
import logging
import logging.handlers
import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import traceback


class JSONFormatter(logging.Formatter):
    """JSON格式的日志formatter"""

    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为JSON"""
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加进程和线程信息
        if hasattr(record, 'process') and hasattr(record, 'thread'):
            log_entry["process_id"] = record.process
            log_entry["thread_id"] = record.thread

        # 添加异常信息
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info)
            }

        # 添加额外字段
        if self.include_extra:
            for key, value in record.__dict__.items():
                if key not in ('name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                             'filename', 'module', 'lineno', 'funcName', 'created',
                             'msecs', 'relativeCreated', 'thread', 'threadName',
                             'processName', 'process', 'exc_info', 'exc_text', 'stack_info'):
                    try:
                        # 尝试JSON序列化值
                        json.dumps(value)
                        log_entry[key] = value
                    except (TypeError, ValueError):
                        # 如果无法序列化，转为字符串
                        log_entry[key] = str(value)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ColoredConsoleFormatter(logging.Formatter):
    """彩色控制台输出formatter"""

    # ANSI颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'        # 重置
    }

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录，添加颜色"""
        # 获取颜色
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        reset = self.COLORS['RESET']

        # 格式化时间
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')

        # 构建日志消息
        log_parts = [
            f"{color}[{timestamp}]",
            f"[{record.levelname}]",
            f"[{record.name}]",
            f"{record.getMessage()}{reset}"
        ]

        # 添加位置信息（对于WARNING及以上级别）
        if record.levelno >= logging.WARNING:
            location = f"{record.filename}:{record.lineno}"
            log_parts.insert(-1, f"[{location}]")

        return " ".join(log_parts)


class LoggingConfig:
    """日志配置管理器"""

    def __init__(
        self,
        app_name: str = "inventory_management",
        log_level: str = "INFO",
        log_dir: Optional[str] = None,
        console_output: bool = True,
        json_format: bool = False,
        max_file_size: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5
    ):
        self.app_name = app_name
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.log_dir = Path(log_dir) if log_dir else Path("logs")
        self.console_output = console_output
        self.json_format = json_format
        self.max_file_size = max_file_size
        self.backup_count = backup_count

        # 确保日志目录存在
        self.log_dir.mkdir(exist_ok=True)

        # 存储已配置的logger
        self._configured_loggers = set()

    def setup_root_logger(self) -> logging.Logger:
        """配置根logger"""
        root_logger = logging.getLogger()

        # 清除现有的handlers
        root_logger.handlers.clear()

        # 设置日志级别
        root_logger.setLevel(self.log_level)

        # 添加控制台handler
        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(self.log_level)

            if self.json_format:
                console_formatter = JSONFormatter()
            else:
                console_formatter = ColoredConsoleFormatter()

            console_handler.setFormatter(console_formatter)
            root_logger.addHandler(console_handler)

        # 添加文件handler
        self._add_file_handlers(root_logger)

        return root_logger

    def _add_file_handlers(self, logger: logging.Logger):
        """添加文件handlers"""
        # 主日志文件 - 包含所有级别
        main_log_file = self.log_dir / f"{self.app_name}.log"
        main_handler = logging.handlers.RotatingFileHandler(
            main_log_file,
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        main_handler.setLevel(logging.DEBUG)

        if self.json_format:
            main_formatter = JSONFormatter()
        else:
            main_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )

        main_handler.setFormatter(main_formatter)
        logger.addHandler(main_handler)

        # 错误日志文件 - 只包含ERROR及以上级别
        error_log_file = self.log_dir / f"{self.app_name}_error.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(main_formatter)
        logger.addHandler(error_handler)

    def get_logger(self, name: str) -> logging.Logger:
        """获取指定名称的logger"""
        logger = logging.getLogger(name)

        # 如果是第一次获取这个logger，进行配置
        if name not in self._configured_loggers:
            logger.setLevel(self.log_level)
            self._configured_loggers.add(name)

        return logger

    def setup_module_logger(
        self,
        module_name: str,
        log_file: Optional[str] = None,
        level: Optional[str] = None
    ) -> logging.Logger:
        """为特定模块设置logger"""
        logger = logging.getLogger(module_name)

        if level:
            logger.setLevel(getattr(logging, level.upper(), self.log_level))
        else:
            logger.setLevel(self.log_level)

        # 如果指定了单独的日志文件
        if log_file:
            file_path = self.log_dir / log_file
            file_handler = logging.handlers.RotatingFileHandler(
                file_path,
                maxBytes=self.max_file_size,
                backupCount=self.backup_count,
                encoding='utf-8'
            )

            if self.json_format:
                formatter = JSONFormatter()
            else:
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                )

            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        self._configured_loggers.add(module_name)
        return logger

    def configure_third_party_loggers(self):
        """配置第三方库的日志级别"""
        # 设置第三方库的日志级别，避免过多的DEBUG信息
        third_party_loggers = {
            'httpx': logging.WARNING,
            'httpcore': logging.WARNING,
            'urllib3': logging.WARNING,
            'requests': logging.WARNING,
            'asyncio': logging.WARNING,
            'lark_oapi': logging.INFO,
        }

        for logger_name, level in third_party_loggers.items():
            logger = logging.getLogger(logger_name)
            logger.setLevel(level)

    def get_logging_stats(self) -> Dict[str, Any]:
        """获取日志统计信息"""
        stats = {
            "configured_loggers": len(self._configured_loggers),
            "log_level": logging.getLevelName(self.log_level),
            "log_dir": str(self.log_dir),
            "json_format": self.json_format,
            "console_output": self.console_output,
        }

        # 统计日志文件大小
        try:
            log_files = {}
            for log_file in self.log_dir.glob("*.log"):
                try:
                    size = log_file.stat().st_size
                    log_files[log_file.name] = {
                        "size_bytes": size,
                        "size_mb": round(size / (1024 * 1024), 2)
                    }
                except Exception:
                    continue

            stats["log_files"] = log_files
        except Exception as e:
            stats["log_files_error"] = str(e)

        return stats

    def setup_error_capture(self):
        """设置全局异常捕获"""
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                # 允许KeyboardInterrupt正常退出
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return

            # 记录未捕获的异常
            logger = self.get_logger("uncaught_exception")
            logger.critical(
                "Uncaught exception",
                exc_info=(exc_type, exc_value, exc_traceback)
            )

        sys.excepthook = handle_exception


# 全局日志配置实例
_logging_config: Optional[LoggingConfig] = None


def setup_logging(
    app_name: str = "inventory_management",
    log_level: str = "INFO",
    log_dir: Optional[str] = None,
    console_output: bool = True,
    json_format: bool = False
) -> LoggingConfig:
    """设置全局日志配置"""
    global _logging_config

    _logging_config = LoggingConfig(
        app_name=app_name,
        log_level=log_level,
        log_dir=log_dir,
        console_output=console_output,
        json_format=json_format
    )

    # 配置根logger
    _logging_config.setup_root_logger()

    # 配置第三方logger
    _logging_config.configure_third_party_loggers()

    # 设置全局异常捕获
    _logging_config.setup_error_capture()

    return _logging_config


def get_logger(name: str) -> logging.Logger:
    """获取logger实例"""
    if _logging_config is None:
        # 如果还没有设置全局配置，使用默认配置
        setup_logging()

    return _logging_config.get_logger(name)


def get_logging_config() -> Optional[LoggingConfig]:
    """获取全局日志配置实例"""
    return _logging_config