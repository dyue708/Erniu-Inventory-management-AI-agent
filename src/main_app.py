"""
优化后的主程序入口
整合所有优化模块，提供健壮的服务管理
"""
import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional, List
import time

# 导入优化后的模块
from config_validator import ApplicationConfig
from logging_config import setup_logging, get_logger
from message_queue import MessageQueue, get_message_queue
from health_monitor import HealthMonitor, get_health_monitor
from exceptions import ConfigurationError, BaseInventoryError, exception_handler
from retry_manager import retry_manager

# 导入原有的业务模块
from message_store_bot import FeishuBot
from message_processor import MessageProcessor

logger = get_logger(__name__)


class ServiceManager:
    """服务管理器 - 负责管理所有后台服务"""

    def __init__(self, config: ApplicationConfig):
        self.config = config
        self.services = {}
        self.tasks = []
        self.shutdown_event = asyncio.Event()
        self.is_shutting_down = False

    async def register_service(self, name: str, service_func, *args, **kwargs):
        """注册服务"""
        self.services[name] = {
            'func': service_func,
            'args': args,
            'kwargs': kwargs,
            'task': None,
            'restart_count': 0,
            'last_restart': None
        }
        logger.info(f"Registered service: {name}")

    async def start_service(self, name: str) -> bool:
        """启动单个服务"""
        if name not in self.services:
            logger.error(f"Service '{name}' not registered")
            return False

        service = self.services[name]

        try:
            # 如果服务已经在运行，先停止
            if service['task'] and not service['task'].done():
                service['task'].cancel()
                try:
                    await service['task']
                except asyncio.CancelledError:
                    pass

            # 启动服务
            service['task'] = asyncio.create_task(
                service['func'](*service['args'], **service['kwargs']),
                name=f"service_{name}"
            )

            self.tasks.append(service['task'])
            logger.info(f"Started service: {name}")
            return True

        except Exception as e:
            logger.error(f"Failed to start service '{name}': {e}")
            return False

    async def start_all_services(self):
        """启动所有服务"""
        logger.info("Starting all services...")

        for name in self.services:
            success = await self.start_service(name)
            if not success:
                logger.error(f"Failed to start service '{name}', continuing with others...")

        logger.info(f"Started {len(self.services)} services")

    async def restart_service(self, name: str, max_restarts: int = 3) -> bool:
        """重启服务"""
        if name not in self.services:
            return False

        service = self.services[name]
        service['restart_count'] += 1
        service['last_restart'] = time.time()

        if service['restart_count'] > max_restarts:
            logger.error(f"Service '{name}' exceeded max restart attempts ({max_restarts})")
            return False

        logger.warning(f"Restarting service '{name}' (attempt {service['restart_count']})")
        return await self.start_service(name)

    async def monitor_services(self):
        """监控服务状态"""
        while not self.is_shutting_down:
            try:
                for name, service in self.services.items():
                    task = service['task']

                    if task and task.done():
                        if task.cancelled():
                            logger.info(f"Service '{name}' was cancelled")
                        elif task.exception():
                            exception = task.exception()
                            logger.error(f"Service '{name}' failed: {exception}")

                            # 尝试重启服务
                            if not self.is_shutting_down:
                                await asyncio.sleep(5)  # 等待5秒后重启
                                await self.restart_service(name)
                        else:
                            logger.warning(f"Service '{name}' completed unexpectedly")

                await asyncio.sleep(10)  # 每10秒检查一次

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Service monitor error: {e}")
                await asyncio.sleep(10)

    async def shutdown_all_services(self, timeout: float = 30.0):
        """优雅关闭所有服务"""
        if self.is_shutting_down:
            return

        self.is_shutting_down = True
        logger.info("Initiating graceful shutdown...")

        # 设置关闭事件
        self.shutdown_event.set()

        # 取消所有任务
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # 等待任务完成
        if self.tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.tasks, return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.warning("Some services did not shutdown gracefully within timeout")

        logger.info("All services shutdown completed")


class InventoryManagementApp:
    """库存管理应用主类"""

    def __init__(self):
        self.config: Optional[ApplicationConfig] = None
        self.service_manager: Optional[ServiceManager] = None
        self.message_queue: Optional[MessageQueue] = None
        self.health_monitor: Optional[HealthMonitor] = None

    async def initialize(self, env_file: Optional[str] = None):
        """初始化应用"""
        try:
            # 1. 加载和验证配置
            logger.info("Loading configuration...")
            self.config = ApplicationConfig(env_file)

            if not self.config.validate_required_configs():
                raise ConfigurationError("Required configuration validation failed")

            logger.info("Configuration loaded and validated successfully")

            # 2. 初始化消息队列
            app_config = self.config.get_app_config()
            message_dir = app_config.get("MESSAGE_DIR", "messages")

            logger.info(f"Initializing message queue in {message_dir}...")
            self.message_queue = get_message_queue(message_dir)

            # 3. 初始化健康监控
            health_port = app_config.get("HEALTH_CHECK_PORT", 8080)
            logger.info(f"Initializing health monitor on port {health_port}...")
            self.health_monitor = get_health_monitor(
                message_queue=self.message_queue,
                port=health_port
            )

            # 4. 初始化服务管理器
            self.service_manager = ServiceManager(self.config)

            logger.info("Application initialized successfully")

        except Exception as e:
            logger.error(f"Application initialization failed: {e}")
            raise

    async def register_services(self):
        """注册所有服务"""
        try:
            feishu_config = self.config.get_feishu_config()

            # 注册飞书消息存储服务
            await self.service_manager.register_service(
                "message_store",
                self._run_message_store_service,
                feishu_config
            )

            # 注册消息处理服务
            app_config = self.config.get_app_config()
            await self.service_manager.register_service(
                "message_processor",
                self._run_message_processor_service,
                app_config.get("MESSAGE_DIR", "messages"),
                feishu_config
            )

            # 注册健康监控服务
            await self.service_manager.register_service(
                "health_monitor",
                self._run_health_monitor_service
            )

            # 注册健康监控Web服务
            await self.service_manager.register_service(
                "health_web_server",
                self._run_health_web_server
            )

            # 注册服务监控
            await self.service_manager.register_service(
                "service_monitor",
                self.service_manager.monitor_services
            )

            logger.info("All services registered successfully")

        except Exception as e:
            logger.error(f"Service registration failed: {e}")
            raise

    @exception_handler(reraise=True)
    async def _run_message_store_service(self, feishu_config: dict):
        """运行飞书消息存储服务"""
        try:
            from async_message_store import AsyncFeishuBot
            bot = AsyncFeishuBot(feishu_config)
            logger.info("Message store service started")
            await bot.start()

            # 等待关闭信号
            await bot.wait_for_shutdown()

        except Exception as e:
            logger.error(f"Message store service error: {e}")
            raise

    @exception_handler(reraise=True)
    async def _run_message_processor_service(self, message_dir: str, feishu_config: dict):
        """运行消息处理服务"""
        try:
            processor = MessageProcessor(
                message_dir=message_dir,
                app_id=feishu_config["APP_ID"],
                app_secret=feishu_config["APP_SECRET"]
            )
            logger.info("Message processor service started")
            await processor.run()
        except Exception as e:
            logger.error(f"Message processor service error: {e}")
            raise

    @exception_handler(reraise=True)
    async def _run_health_monitor_service(self):
        """运行健康监控服务"""
        try:
            logger.info("Health monitor service started")
            await self.health_monitor.start_monitoring()
        except Exception as e:
            logger.error(f"Health monitor service error: {e}")
            raise

    @exception_handler(reraise=True)
    async def _run_health_web_server(self):
        """运行健康监控Web服务器"""
        try:
            runner = await self.health_monitor.start_web_server()
            logger.info("Health web server service started")

            # 等待关闭信号
            await self.service_manager.shutdown_event.wait()

            # 清理Web服务器
            await runner.cleanup()
            logger.info("Health web server stopped")

        except Exception as e:
            logger.error(f"Health web server service error: {e}")
            raise

    async def start(self):
        """启动应用"""
        try:
            logger.info("Starting Inventory Management Application...")

            # 启动所有服务
            await self.service_manager.start_all_services()

            logger.info("Application started successfully")
            logger.info("Press Ctrl+C to stop the application")

            # 等待中断信号
            await self.wait_for_shutdown()

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Application start failed: {e}")
            raise
        finally:
            await self.shutdown()

    async def wait_for_shutdown(self):
        """等待关闭信号"""
        try:
            # 设置信号处理器
            loop = asyncio.get_running_loop()

            def signal_handler():
                logger.info("Received shutdown signal")
                self.service_manager.shutdown_event.set()

            # 在Windows上只支持SIGINT
            if sys.platform != 'win32':
                loop.add_signal_handler(signal.SIGTERM, signal_handler)
                loop.add_signal_handler(signal.SIGINT, signal_handler)
            else:
                # Windows上使用不同的方式处理信号
                signal.signal(signal.SIGINT, lambda s, f: signal_handler())

            # 等待关闭事件
            await self.service_manager.shutdown_event.wait()

        except Exception as e:
            logger.error(f"Error waiting for shutdown: {e}")

    async def shutdown(self):
        """关闭应用"""
        try:
            logger.info("Shutting down application...")

            if self.service_manager:
                await self.service_manager.shutdown_all_services()

            # 清理消息队列
            if self.message_queue:
                await self.message_queue.cleanup_old_messages()

            logger.info("Application shutdown completed")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


async def main():
    """主函数"""
    app = None

    try:
        # 设置日志
        log_config = setup_logging(
            app_name="inventory_management",
            log_level="INFO",
            console_output=True,
            json_format=False
        )

        logger.info("=== Inventory Management System Starting ===")

        # 创建应用实例
        app = InventoryManagementApp()

        # 初始化应用
        await app.initialize()

        # 注册服务
        await app.register_services()

        # 启动应用
        await app.start()

    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except BaseInventoryError as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if app:
            try:
                await app.shutdown()
            except Exception as e:
                logger.error(f"Error during final shutdown: {e}")

        logger.info("=== Inventory Management System Stopped ===")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)