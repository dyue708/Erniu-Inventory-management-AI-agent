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
        bot.start()
    except Exception as e:
        logger.error(f"Message store bot error: {str(e)}", exc_info=True)

def run_message_processor():
    """在独立线程中运行消息处理器"""
    try:
        processor = MessageProcessor(
            app_id=FEISHU_CONFIG["APP_ID"],
            app_secret=FEISHU_CONFIG["APP_SECRET"]
        )
        processor.process_messages()
    except Exception as e:
        logger.error(f"Message processor error: {str(e)}", exc_info=True)

def main():
    """主函数：使用线程并发运行两个服务"""
    # 创建事件用于优雅退出
    stop_event = threading.Event()
    processors = []
    
    try:
        # 创建服务实例
        bot = FeishuBot(config=FEISHU_CONFIG)
        processor = MessageProcessor(
            app_id=FEISHU_CONFIG["APP_ID"],
            app_secret=FEISHU_CONFIG["APP_SECRET"]
        )
        
        # 创建并启动线程
        threads = [
            threading.Thread(target=bot.start, name="MessageStore"),
            AsyncThread(processor.process_messages, name="MessageProcessor")  # 使用 AsyncThread
        ]
        
        for thread in threads:
            thread.daemon = True
            thread.start()
            processors.append(thread)
        
        # 等待中断信号
        while True:
            for thread in threads:
                if not thread.is_alive():
                    logger.error(f"Thread {thread.name} died unexpectedly")
                    return
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        # 触发清理操作
        if hasattr(bot, 'stop'):
            bot.stop()
        if hasattr(processor, 'stop'):
            processor.stop()
        
        # 等待线程完成
        for thread in threads:
            thread.join(timeout=5)
            
        logger.info("Shutdown complete")
    except Exception as e:
        logger.error(f"Main program error: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main() 