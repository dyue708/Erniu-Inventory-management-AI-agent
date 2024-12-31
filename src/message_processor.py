import os
import time
import json
from pathlib import Path
import logging
from lark_oapi import Client
from config import FEISHU_CONFIG

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

    def process_messages(self):
        logger.info("Starting message processing loop")
        while True:
            message_files = [f for f in self.message_dir.glob("*.json") 
                           if f not in self.processed_files]
            
            if message_files:
                logger.info("Found %d new message files to process", len(message_files))

            for msg_file in message_files:
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
                        
                        logger.info("Received message from %s: %s", sender_open_id, original_text)
                        
                        # 直接发送原始文本，不做额外处理
                        if self.send_message(sender_open_id, original_text):
                            logger.info("Reply sent successfully")
                        else:
                            logger.error("Failed to send reply")
                    
                    # 处理完成后删除文件
                    os.remove(msg_file)
                    self.processed_files.add(msg_file)
                    logger.info("Successfully processed and removed file: %s", msg_file)
                    
                except Exception as e:
                    logger.error("Error processing file %s: %s", msg_file, str(e))
                    continue
            
            time.sleep(2)

if __name__ == "__main__":
    processor = MessageProcessor(
        app_id=FEISHU_CONFIG["APP_ID"],
        app_secret=FEISHU_CONFIG["APP_SECRET"], 
        message_dir=Path("messages")
    )
    processor.process_messages()
