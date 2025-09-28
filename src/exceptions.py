"""
统一异常处理模块
"""
import functools
import logging
import traceback
from typing import Any, Callable, Optional, Type, Union
from enum import Enum


class ErrorCode(Enum):
    """错误码枚举"""
    # 通用错误
    UNKNOWN_ERROR = "E0001"
    VALIDATION_ERROR = "E0002"
    CONFIGURATION_ERROR = "E0003"

    # 网络相关错误
    NETWORK_ERROR = "E1001"
    API_TIMEOUT = "E1002"
    API_RATE_LIMIT = "E1003"

    # 飞书相关错误
    FEISHU_AUTH_ERROR = "E2001"
    FEISHU_API_ERROR = "E2002"
    FEISHU_PERMISSION_ERROR = "E2003"

    # AI相关错误
    AI_API_ERROR = "E3001"
    AI_RESPONSE_ERROR = "E3002"

    # 业务逻辑错误
    INVENTORY_ERROR = "E4001"
    PRODUCT_NOT_FOUND = "E4002"
    WAREHOUSE_NOT_FOUND = "E4003"
    INSUFFICIENT_STOCK = "E4004"


class BaseInventoryError(Exception):
    """基础异常类"""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        details: Optional[dict] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None
        }


class ValidationError(BaseInventoryError):
    """参数验证错误"""

    def __init__(self, message: str, field: str = None, **kwargs):
        super().__init__(message, ErrorCode.VALIDATION_ERROR, **kwargs)
        if field:
            self.details["field"] = field


class ConfigurationError(BaseInventoryError):
    """配置错误"""

    def __init__(self, message: str, config_key: str = None, **kwargs):
        super().__init__(message, ErrorCode.CONFIGURATION_ERROR, **kwargs)
        if config_key:
            self.details["config_key"] = config_key


class NetworkError(BaseInventoryError):
    """网络相关错误"""

    def __init__(self, message: str, url: str = None, status_code: int = None, **kwargs):
        super().__init__(message, ErrorCode.NETWORK_ERROR, **kwargs)
        if url:
            self.details["url"] = url
        if status_code:
            self.details["status_code"] = status_code


class FeishuError(BaseInventoryError):
    """飞书API相关错误"""

    def __init__(self, message: str, api_code: int = None, **kwargs):
        super().__init__(message, ErrorCode.FEISHU_API_ERROR, **kwargs)
        if api_code:
            self.details["api_code"] = api_code


class AIError(BaseInventoryError):
    """AI相关错误"""

    def __init__(self, message: str, model: str = None, **kwargs):
        super().__init__(message, ErrorCode.AI_API_ERROR, **kwargs)
        if model:
            self.details["model"] = model


class InventoryBusinessError(BaseInventoryError):
    """库存业务逻辑错误"""

    def __init__(self, message: str, product_id: str = None, warehouse_id: str = None, **kwargs):
        super().__init__(message, ErrorCode.INVENTORY_ERROR, **kwargs)
        if product_id:
            self.details["product_id"] = product_id
        if warehouse_id:
            self.details["warehouse_id"] = warehouse_id


def exception_handler(
    logger: Optional[logging.Logger] = None,
    reraise: bool = True,
    default_return: Any = None,
    handled_exceptions: tuple = (Exception,)
):
    """
    异常处理装饰器

    Args:
        logger: 日志记录器
        reraise: 是否重新抛出异常
        default_return: 异常时的默认返回值
        handled_exceptions: 要处理的异常类型
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except handled_exceptions as e:
                error_msg = f"Error in {func.__name__}: {str(e)}"

                if logger:
                    if isinstance(e, BaseInventoryError):
                        logger.error(error_msg, extra={"error_details": e.to_dict()})
                    else:
                        logger.error(error_msg, exc_info=True)

                if reraise:
                    raise
                return default_return

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except handled_exceptions as e:
                error_msg = f"Error in {func.__name__}: {str(e)}"

                if logger:
                    if isinstance(e, BaseInventoryError):
                        logger.error(error_msg, extra={"error_details": e.to_dict()})
                    else:
                        logger.error(error_msg, exc_info=True)

                if reraise:
                    raise
                return default_return

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def safe_execute(
    func: Callable,
    *args,
    logger: Optional[logging.Logger] = None,
    default_return: Any = None,
    **kwargs
) -> Any:
    """
    安全执行函数，捕获所有异常

    Args:
        func: 要执行的函数
        logger: 日志记录器
        default_return: 异常时的默认返回值
        *args, **kwargs: 函数参数

    Returns:
        函数执行结果或默认返回值
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_msg = f"Error executing {func.__name__}: {str(e)}"

        if logger:
            if isinstance(e, BaseInventoryError):
                logger.error(error_msg, extra={"error_details": e.to_dict()})
            else:
                logger.error(error_msg, exc_info=True)
        else:
            print(f"ERROR: {error_msg}")
            print(traceback.format_exc())

        return default_return


# 为了避免循环导入，在这里导入asyncio
import asyncio