"""
重试和错误处理管理器
"""
import asyncio
import random
import time
import logging
from typing import Callable, Any, Optional, Type, Union, Tuple
from functools import wraps
import httpx
from exceptions import NetworkError, BaseInventoryError

logger = logging.getLogger(__name__)


class RetryConfig:
    """重试配置"""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        backoff_strategy: str = "exponential"  # exponential, linear, fixed
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.backoff_strategy = backoff_strategy

    def calculate_delay(self, attempt: int) -> float:
        """计算延迟时间"""
        if self.backoff_strategy == "exponential":
            delay = self.base_delay * (self.exponential_base ** (attempt - 1))
        elif self.backoff_strategy == "linear":
            delay = self.base_delay * attempt
        else:  # fixed
            delay = self.base_delay

        # 应用最大延迟限制
        delay = min(delay, self.max_delay)

        # 添加抖动
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)

        return delay


class CircuitBreaker:
    """熔断器"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Type[Exception] = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """调用函数，应用熔断逻辑"""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info("Circuit breaker moving to HALF_OPEN state")
            else:
                raise NetworkError("Circuit breaker is OPEN")

        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                logger.info("Circuit breaker reset to CLOSED state")
            return result
        except self.expected_exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

            raise


class RetryManager:
    """重试管理器"""

    def __init__(self, default_config: Optional[RetryConfig] = None):
        self.default_config = default_config or RetryConfig()
        self.circuit_breakers = {}

    def get_circuit_breaker(self, name: str) -> CircuitBreaker:
        """获取或创建熔断器"""
        if name not in self.circuit_breakers:
            self.circuit_breakers[name] = CircuitBreaker()
        return self.circuit_breakers[name]

    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        config: Optional[RetryConfig] = None,
        circuit_breaker_name: Optional[str] = None,
        retriable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
        **kwargs
    ) -> Any:
        """
        异步执行函数并处理重试

        Args:
            func: 要执行的函数
            config: 重试配置
            circuit_breaker_name: 熔断器名称
            retriable_exceptions: 可重试的异常类型
            *args, **kwargs: 函数参数

        Returns:
            函数执行结果
        """
        retry_config = config or self.default_config
        circuit_breaker = None

        if circuit_breaker_name:
            circuit_breaker = self.get_circuit_breaker(circuit_breaker_name)

        last_exception = None

        for attempt in range(1, retry_config.max_attempts + 1):
            try:
                # 应用熔断器
                if circuit_breaker:
                    if asyncio.iscoroutinefunction(func):
                        result = await circuit_breaker.call(func, *args, **kwargs)
                    else:
                        result = circuit_breaker.call(func, *args, **kwargs)
                else:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    else:
                        result = func(*args, **kwargs)

                if attempt > 1:
                    logger.info(f"Function succeeded on attempt {attempt}")

                return result

            except BaseException as e:
                last_exception = e

                # 检查是否是可重试的异常
                if not isinstance(e, retriable_exceptions):
                    logger.error(f"Non-retriable exception: {type(e).__name__}: {e}")
                    raise

                if attempt == retry_config.max_attempts:
                    logger.error(f"All {retry_config.max_attempts} attempts failed")
                    break

                delay = retry_config.calculate_delay(attempt)
                logger.warning(
                    f"Attempt {attempt} failed: {type(e).__name__}: {e}. "
                    f"Retrying in {delay:.2f} seconds..."
                )

                await asyncio.sleep(delay)

        # 所有重试都失败了
        if isinstance(last_exception, BaseInventoryError):
            raise last_exception
        else:
            raise NetworkError(
                f"Operation failed after {retry_config.max_attempts} attempts",
                cause=last_exception
            )

    def execute_with_retry_sync(
        self,
        func: Callable,
        *args,
        config: Optional[RetryConfig] = None,
        circuit_breaker_name: Optional[str] = None,
        retriable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
        **kwargs
    ) -> Any:
        """
        同步执行函数并处理重试
        """
        retry_config = config or self.default_config
        circuit_breaker = None

        if circuit_breaker_name:
            circuit_breaker = self.get_circuit_breaker(circuit_breaker_name)

        last_exception = None

        for attempt in range(1, retry_config.max_attempts + 1):
            try:
                # 应用熔断器
                if circuit_breaker:
                    result = circuit_breaker.call(func, *args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                if attempt > 1:
                    logger.info(f"Function succeeded on attempt {attempt}")

                return result

            except BaseException as e:
                last_exception = e

                # 检查是否是可重试的异常
                if not isinstance(e, retriable_exceptions):
                    logger.error(f"Non-retriable exception: {type(e).__name__}: {e}")
                    raise

                if attempt == retry_config.max_attempts:
                    logger.error(f"All {retry_config.max_attempts} attempts failed")
                    break

                delay = retry_config.calculate_delay(attempt)
                logger.warning(
                    f"Attempt {attempt} failed: {type(e).__name__}: {e}. "
                    f"Retrying in {delay:.2f} seconds..."
                )

                time.sleep(delay)

        # 所有重试都失败了
        if isinstance(last_exception, BaseInventoryError):
            raise last_exception
        else:
            raise NetworkError(
                f"Operation failed after {retry_config.max_attempts} attempts",
                cause=last_exception
            )


def retry_on_failure(
    config: Optional[RetryConfig] = None,
    circuit_breaker_name: Optional[str] = None,
    retriable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """重试装饰器"""
    retry_manager = RetryManager()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await retry_manager.execute_with_retry(
                func, *args,
                config=config,
                circuit_breaker_name=circuit_breaker_name,
                retriable_exceptions=retriable_exceptions,
                **kwargs
            )

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return retry_manager.execute_with_retry_sync(
                func, *args,
                config=config,
                circuit_breaker_name=circuit_breaker_name,
                retriable_exceptions=retriable_exceptions,
                **kwargs
            )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# 预定义的重试配置
NETWORK_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=10.0,
    backoff_strategy="exponential"
)

API_RETRY_CONFIG = RetryConfig(
    max_attempts=5,
    base_delay=2.0,
    max_delay=30.0,
    backoff_strategy="exponential"
)

QUICK_RETRY_CONFIG = RetryConfig(
    max_attempts=2,
    base_delay=0.5,
    max_delay=2.0,
    backoff_strategy="fixed"
)

# 全局重试管理器实例
retry_manager = RetryManager()


# HTTP客户端重试配置
def create_http_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """创建带重试配置的HTTP客户端"""
    transport = httpx.AsyncHTTPTransport(
        retries=2,
        verify=True
    )

    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        transport=transport,
        limits=httpx.Limits(
            max_keepalive_connections=10,
            max_connections=20
        )
    )