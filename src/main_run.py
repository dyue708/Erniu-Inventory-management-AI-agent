import threading
import logging
import asyncio
from message_store_bot import FeishuBot
from message_processor import MessageProcessor
from config import FEISHU_CONFIG
import time

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AsyncThread(threading.Thread):
    """用于在线程中运行异步函数的特殊线程类"""
    def __init__(self, func, name):
        super().__init__()
        self.func = func
        self.name = name
        self.daemon = True

    def run(self):
        asyncio.run(self.func())

def run_message_store():
    """在独立线程中运行消息存储机器人"""
    try:
        bot = FeishuBot(config=FEISHU_CONFIG)
        logger.info("Message store bot started")
        bot.start()
    except Exception as e:
        logger.error(f"Message store bot error: {str(e)}", exc_info=True)
        # 添加重试逻辑
        time.sleep(5)  # 等待5秒后重试
        run_message_store()  # 递归重试

def run_message_processor():
    """在独立线程中运行消息处理器"""
    try:
        processor = MessageProcessor()
        logger.info("Message processor started")
        asyncio.run(processor.run())
    except Exception as e:
        logger.error(f"Message processor error: {str(e)}", exc_info=True)
        # 添加重试逻辑
        time.sleep(5)  # 等待5秒后重试
        run_message_processor()  # 递归重试

def main():
    """主函数：使用线程并发运行两个服务"""
    try:
        # 创建并启动线程
        threads = [
            threading.Thread(target=run_message_store, name="MessageStore", daemon=True),
            threading.Thread(target=run_message_processor, name="MessageProcessor", daemon=True)
        ]
        
        for thread in threads:
            thread.start()
            logger.info(f"Started thread: {thread.name}")
        
        # 等待中断信号
        while True:
            alive_threads = [t for t in threads if t.is_alive()]
            if not alive_threads:
                logger.error("All threads died unexpectedly")
                return
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        # 等待线程完成
        for thread in threads:
            thread.join(timeout=5)
            
        logger.info("Shutdown complete")
    except Exception as e:
        logger.error(f"Main program error: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main() 