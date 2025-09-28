"""
异步消息存储适配器
解决飞书SDK事件循环冲突问题
"""
import asyncio
import threading
import logging
from typing import Optional
from message_store_bot import FeishuBot

logger = logging.getLogger(__name__)


class AsyncFeishuBot:
    """异步飞书机器人适配器"""

    def __init__(self, config: dict):
        self.config = config
        self.bot: Optional[FeishuBot] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False
        self._stop_event = threading.Event()

    def _run_bot_in_thread(self):
        """在独立线程中运行飞书机器人"""
        try:
            logger.info("Starting Feishu bot in dedicated thread")
            self.bot = FeishuBot(config=self.config)

            # 在独立线程中启动机器人
            self.is_running = True
            self.bot.start()

        except Exception as e:
            logger.error(f"Feishu bot thread error: {e}")
            self.is_running = False
        finally:
            logger.info("Feishu bot thread stopped")
            self.is_running = False

    async def start(self):
        """异步启动飞书机器人"""
        if self.is_running:
            logger.warning("Feishu bot is already running")
            return

        # 在独立线程中启动机器人
        self.thread = threading.Thread(
            target=self._run_bot_in_thread,
            name="FeishuBot",
            daemon=True
        )
        self.thread.start()

        # 等待机器人启动
        max_wait = 10  # 最多等待10秒
        wait_time = 0
        while not self.is_running and wait_time < max_wait:
            await asyncio.sleep(0.5)
            wait_time += 0.5

        if self.is_running:
            logger.info("Feishu bot started successfully in async mode")
        else:
            raise Exception("Failed to start Feishu bot within timeout")

    async def stop(self):
        """异步停止飞书机器人"""
        if not self.is_running:
            return

        logger.info("Stopping Feishu bot...")
        self._stop_event.set()

        # 等待线程结束
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

        self.is_running = False
        logger.info("Feishu bot stopped")

    def is_healthy(self) -> bool:
        """检查机器人是否健康运行"""
        return self.is_running and (self.thread and self.thread.is_alive())

    async def wait_for_shutdown(self):
        """等待关闭信号"""
        while self.is_running:
            if self._stop_event.is_set():
                break
            await asyncio.sleep(1)

        await self.stop()


# 全局异步机器人实例
_async_bot: Optional[AsyncFeishuBot] = None


def get_async_feishu_bot(config: dict) -> AsyncFeishuBot:
    """获取全局异步飞书机器人实例"""
    global _async_bot
    if _async_bot is None:
        _async_bot = AsyncFeishuBot(config)
    return _async_bot