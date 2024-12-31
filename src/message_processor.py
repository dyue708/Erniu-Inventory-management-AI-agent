import os
import time
import json
from pathlib import Path
import logging
from lark_oapi import Client
from config import FEISHU_CONFIG
from deepseek_chat import DeepSeekChat
import asyncio

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MessageProcessor:
    def __init__(self, message_dir="messages", app_id=None, app_secret=None):
        self.message_dir = Path(message_dir)
        self.message_dir.mkdir(exist_ok=True)
        self.processed_files = set()
        self.app_id = app_id or FEISHU_CONFIG["APP_ID"]
        self.app_secret = app_secret or FEISHU_CONFIG["APP_SECRET"]
        
        # 初始化飞书客户端
        self.client = Client.builder() \
            .app_id(self.app_id) \
            .app_secret(self.app_secret) \
            .build()
        logger.info("MessageProcessor initialized with app_id: %s", self.app_id)
        
        # 添加停止标志
        self._should_stop = False
        self.deepseek = DeepSeekChat()

    def send_message(self, open_id, content):
        try:
            logger.info("Attempting to send message to open_id: %s", open_id)
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

            # 使用 builder 模式构建请求体
            request_body = CreateMessageRequestBody.builder() \
                .receive_id(open_id) \
                .msg_type("text") \
                .content(json.dumps({"text": content}, ensure_ascii=False)) \
                .build()

            # 构建完整请求
            request = CreateMessageRequest.builder() \
                .receive_id_type("open_id") \
                .request_body(request_body) \
                .build()

            logger.info("Sending request...")
            response = self.client.im.v1.message.create(request)
            
            # 详细记录响应信息
            if not response.success():
                logger.error(
                    f"Send message failed, code: {response.code}, "
                    f"msg: {response.msg}, "
                    f"log_id: {response.get_log_id()}"
                )
                return False
            
            logger.info("Message sent successfully")
            return True

        except Exception as e:
            logger.error("Error sending message: %s", str(e), exc_info=True)
            return False

    def stop(self):
        """安全停止处理循环"""
        self._should_stop = True
        logger.info("Message processor stopping...")

    async def process_messages(self):
        logger.info("Starting message processing loop")
        while not self._should_stop:  # 使用停止标志
            try:
                # 遍历所有用户目录
                user_dirs = [d for d in self.message_dir.iterdir() if d.is_dir()]
                
                for user_dir in user_dirs:
                    # 获取该用户的所有未处理消息
                    message_files = [
                        f for f in user_dir.glob("*.json") 
                        if f not in self.processed_files
                    ]
                    
                    if message_files:
                        logger.info("Found %d new message files for user %s", 
                                  len(message_files), user_dir.name)

                    # 按时间顺序处理消息
                    for msg_file in sorted(message_files):
                        try:
                            logger.info("Processing file: %s", msg_file)
                            with open(msg_file, 'r', encoding='utf-8') as f:
                                message = json.load(f)
                            
                            # 解析飞书消息格式
                            if message.get("type") == "p2p_message":
                                event_data = json.loads(message["data"])
                                sender_open_id = event_data["event"]["sender"]["sender_id"]["open_id"]
                                message_content = json.loads(event_data["event"]["message"]["content"])
                                original_text = message_content.get("text", "")
                                
                                logger.info("Received message from %s: %s", 
                                          sender_open_id, original_text)
                                
                                # Get AI response
                                ai_response = await self.deepseek.chat(original_text, sender_open_id)
                                
                                # Send AI response back to user
                                if self.send_message(sender_open_id, ai_response):
                                    logger.info("AI reply sent successfully")
                                else:
                                    logger.error("Failed to send AI reply")
                            
                            # 处理完成后删除文件
                            os.remove(msg_file)
                            self.processed_files.add(msg_file)
                            logger.info("Successfully processed and removed file: %s", 
                                      msg_file)
                            
                        except Exception as e:
                            logger.error("Error processing file %s: %s", msg_file, str(e))
                            continue
                    
                # 将 sleep 移到循环末尾，并增加可配置性
                time.sleep(self.poll_interval if hasattr(self, 'poll_interval') else 2)
                
            except Exception as e:
                logger.error("Error in process_messages loop: %s", str(e), exc_info=True)
                # 添加短暂延迟，避免在错误情况下的快速循环
                time.sleep(0.5)
                continue

if __name__ == "__main__":
    processor = MessageProcessor(
        app_id=FEISHU_CONFIG["APP_ID"],
        app_secret=FEISHU_CONFIG["APP_SECRET"], 
        message_dir=Path("messages")
    )
    asyncio.run(processor.process_messages())
