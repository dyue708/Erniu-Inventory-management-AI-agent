import os
import time
import json
from pathlib import Path
import logging
from lark_oapi import Client
from config import FEISHU_CONFIG
from deepseek_chat import DeepSeekChat
import asyncio
import re
from datetime import datetime
from table_manage import WarehouseManager, ProductManager, InboundManager, InventorySummaryManager
from asyncio import Lock
from collections import defaultdict
from lark_oapi.api.im.v1 import *

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
        self.warehouse_mgr = WarehouseManager()
        self.product_mgr = ProductManager()
        self.running = True  # 控制处理循环
        self.sleep_interval = 1  # 无消息时的休眠时间（秒）
        
        # 添加用户锁字典
        self.user_locks = defaultdict(Lock)

    async def run(self):
        """运行消息处理循环"""
        while self.running:
            try:
                # 处理消息
                await self.process_messages()
                
                # 无消息时休眠一段时间
                time.sleep(self.sleep_interval)
                
            except Exception as e:
                logger.error(f"消息处理循环发生错误: {e}")
                # 发生错误时稍微延长休眠时间
                time.sleep(self.sleep_interval * 2)
                continue  # 继续循环

    def stop(self):
        """停止消息处理"""
        self.running = False

    async def process_messages(self):
        """处理消息（异步方法）"""
        logger.info("Starting message processing loop")
        while not self._should_stop:
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
                            if message.get("type") == "card.action.trigger":
                                event_data = message.get("event", {})
                                action = event_data.get("action", {})
                                operator = event_data.get("operator", {})
                                operator_id = operator.get("open_id")
                                message_id = event_data.get("message_id")  # 获取消息ID
                                
                                if action.get("tag") == "button":
                                    value = action.get("value", {})
                                    if value.get("form_type") == "inbound" and value.get("tag") == "submit":
                                        try:
                                            # 获取表单数据
                                            form_data = action.get("form_data", {})
                                            warehouse_data = json.loads(form_data.get("warehouse", "{}"))
                                            product_data = json.loads(form_data.get("product", "{}"))
                                            quantity = float(form_data.get("quantity", 0))
                                            price = float(form_data.get("price", 0))
                                            supplier = form_data.get("supplier", "")
                                            tracking = form_data.get("tracking", "")
                                            phone = form_data.get("phone", "")
                                            batch_complete = value.get("batch_complete", True)
                                            current_time = int(datetime.now().timestamp() * 1000)

                                            # 构造入库数据
                                            inbound_data = [{
                                                "fields": {
                                                    "入库日期": current_time,
                                                    "快递单号": tracking,
                                                    "快递手机号": phone,
                                                    "供应商": supplier,
                                                    "商品ID": product_data.get("product_id"),
                                                    "商品名称": product_data.get("product_name"),
                                                    "入库数量": quantity,
                                                    "入库单价": price,
                                                    "仓库名": warehouse_data.get("warehouse"),
                                                    "仓库备注": warehouse_data.get("warehouse_note"),
                                                    "仓库地址": warehouse_data.get("warehouse_address"),
                                                    "操作者ID": operator_id,
                                                    "操作时间": current_time
                                                }
                                            }]

                                            # 记录入库信息
                                            logger.info(f"Processing inbound submission: {json.dumps(inbound_data, ensure_ascii=False)}")
                                            
                                            # 使用入库管理器处理入库
                                            inbound_mgr = InboundManager()
                                            if await asyncio.to_thread(inbound_mgr.add_inbound, inbound_data):
                                                # 构造已禁用的卡片
                                                disabled_card = self.generate_disabled_inbound_form(
                                                    warehouse_data=warehouse_data,
                                                    product_data=product_data,
                                                    quantity=quantity,
                                                    price=price,
                                                    supplier=supplier,
                                                    tracking=tracking,
                                                    phone=phone
                                                )
                                                
                                                # 更新卡片消息
                                                await self.update_card_message(
                                                    message_id=message_id,
                                                    card_content=disabled_card
                                                )
                                                
                                                # 发送成功消息
                                                await self.send_text_message(
                                                    receive_id=operator_id,
                                                    content="✅ 入库信息已提交成功！"
                                                )

                                                # 如果不是批次完成，则生成新的入库表单
                                                if not batch_complete:
                                                    tracking_info = {
                                                        "tracking": tracking,
                                                        "phone": phone
                                                    }
                                                    new_card = self.generate_inbound_form(tracking_info=tracking_info)
                                                    if new_card:
                                                        await self.send_card_message(
                                                            receive_id=operator_id,
                                                            card_content=new_card
                                                        )
                                            else:
                                                raise Exception("入库处理失败")

                                        except Exception as e:
                                            logger.error(f"处理入库提交失败: {e}")
                                            await self.send_text_message(
                                                receive_id=operator_id,
                                                content=f"❌ 入库提交失败: {str(e)}\n请重试或联系管理员"
                                            )
                                    
                                    elif value.get("form_type") == "inbound" and value.get("tag") == "next":
                                        # 处理"入库下一个商品"的逻辑
                                        try:
                                            # 生成新的入库表单
                                            card = self.generate_inbound_form()
                                            if card:
                                                await self.send_card_message(
                                                    receive_id=operator_id,
                                                    card_content=card
                                                )
                                            else:
                                                await self.send_text_message(
                                                    receive_id=operator_id,
                                                    content="❌ 生成新表单失败，请重试"
                                                )
                                        except Exception as e:
                                            logger.error(f"生成新表单失败: {e}")
                                            await self.send_text_message(
                                                receive_id=operator_id,
                                                content="❌ 生成新表单失败，请重试"
                                            )
                            elif message.get("type") in ["p2p_message", "message"]:  # 添加 "message" 类型支持群消息
                                event_data = json.loads(message["data"])
                                event = event_data["event"]
                                message_type = event["message"]["chat_type"]
                                
                                # 获取发送者 ID 和消息内容
                                sender_open_id = event["sender"]["sender_id"]["open_id"]
                                message_content = json.loads(event["message"]["content"])
                                original_text = message_content.get("text", "")
                                
                                # 确定接收者 ID 和类型
                                if message_type == "group":
                                    receive_id = event["message"]["chat_id"]
                                    chat_type = "group"
                                else:
                                    receive_id = sender_open_id
                                    chat_type = "p2p"
                                
                                logger.info("Received %s message from %s: %s", 
                                          chat_type, sender_open_id, original_text)
                                
                                # 使用用户锁确保顺序处理
                                async with self.user_locks[sender_open_id]:
                                    # Get AI response
                                    ai_response = await self.deepseek.chat(original_text, sender_open_id)
                                    
                                    # 提取用户可读的消息（去除JSON部分）
                                    user_message = self._extract_user_message(ai_response)
                                    
                                    # For group chats, mention the sender
                                    if chat_type == "group":
                                        user_message = f"<at user_id=\"{sender_open_id}\"></at>\n{user_message}"
                                    
                                    # Send AI response back
                                    success = await self.send_message(receive_id, user_message, chat_type)
                                    if success:
                                        logger.info("AI reply sent successfully")
                                    else:
                                        logger.error("Failed to send AI reply")
                                        continue  # 如果发送失败，跳过文件删除
                            
                            elif message.get("type") == "bot_menu_event":
                                event_data = json.loads(message["data"])
                                event = event_data["event"]
                                if event.get("event_key") == "INBOUND":
                                    receive_id = event["operator"]["operator_id"]["open_id"]
                                    
                                    # 生成入库表单卡片
                                    card = self.generate_inbound_form()
                                    if card:
                                        # 发送卡片消息
                                        if await self.send_card_message(
                                            receive_id=receive_id,
                                            card_content=card
                                        ):
                                            logger.info("Inbound form card sent successfully")
                                        else:
                                            logger.error("Failed to send inbound form card")
                                            continue  # 如果发送失败，跳过文件删除
                                    else:
                                        # 发送错误消息
                                        if await self.send_text_message(
                                            receive_id=receive_id,
                                            content="❌ 生成入库表单失败，请稍后重试"
                                        ):
                                            logger.info("Error message sent successfully")
                                        else:
                                            logger.error("Failed to send error message")
                                            continue  # 如果发送失败，跳过文件删除
                            
                            # 只有在消息处理成功后才删除文件
                            os.remove(msg_file)
                            self.processed_files.add(msg_file)
                            logger.info("Successfully processed and removed file: %s", 
                                      msg_file)
                            
                        except Exception as e:
                            logger.error("Error processing file %s: %s", msg_file, str(e))
                            continue
                    
                # 将 sleep 移到循环末尾，并增加可配置性
                await asyncio.sleep(self.poll_interval if hasattr(self, 'poll_interval') else 2)
                
            except Exception as e:
                logger.error("Error in process_messages loop: %s", str(e), exc_info=True)
                # 添加短暂延迟，避免在错误情况下的快速循环
                await asyncio.sleep(0.5)
                continue

    def _extract_user_message(self, ai_response: str) -> str:
        """从AI响应中提取用户可读的消息部分"""
        # 移除 JSON 部分
        message = re.sub(r'<JSON>.*?</JSON>', '', ai_response, flags=re.DOTALL)
        # 清理多余的空行
        message = '\n'.join(line for line in message.splitlines() if line.strip())
        return message.strip()

    def generate_inbound_form(self, tracking_info=None) -> dict:
        """生成入库表单卡片"""
        try:
            # 获取仓库列表
            warehouse_df = self.warehouse_mgr.get_data()
            warehouse_options = []
            for _, row in warehouse_df.iterrows():
                warehouse_options.append({
                    "text": {
                        "tag": "plain_text",
                        "content": f"{row['仓库名']} - {row['仓库备注']}"
                    },
                    "value": json.dumps({
                        "warehouse": row['仓库名'],
                        "warehouse_note": row['仓库备注'],
                        "warehouse_address": row['仓库地址']
                    }, ensure_ascii=False)
                })

            # 获取商品列表
            product_df = self.product_mgr.get_data()
            product_options = []
            for _, row in product_df.iterrows():
                product_options.append({
                    "text": {
                        "tag": "plain_text",
                        "content": f"{row['商品名称']} ({row['商品规格']})"
                    },
                    "value": json.dumps({
                        "product_id": row['商品ID'],
                        "product_name": row['商品名称'],
                        "product_spec": row['商品规格']
                    }, ensure_ascii=False)
                })

            # 构建入库表单卡片
            card = {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "入库表单" if not tracking_info else "入库表单（批次继续）"
                    },
                    "template": "blue"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "请填写以下入库信息："
                        }
                    },
                    # 商品选择
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "**商品选择**"
                        }
                    },
                    {
                        "tag": "select_static",
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "请选择商品"
                        },
                        "value": {
                            "key": "product"
                        },
                        "options": product_options
                    },
                    # 数量和单价
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "**数量和单价**"
                        }
                    },
                    {
                        "tag": "input",
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "请输入数量"
                        },
                        "value": {
                            "key": "quantity"
                        },
                        "type": "number"
                    },
                    {
                        "tag": "input",
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "请输入单价"
                        },
                        "value": {
                            "key": "price"
                        },
                        "type": "number"
                    },
                    # 仓库选择
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "**仓库选择**"
                        }
                    },
                    {
                        "tag": "select_static",
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "请选择仓库"
                        },
                        "value": {
                            "key": "warehouse"
                        },
                        "options": warehouse_options
                    },
                    # 供应商信息
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "**供应商信息**"
                        }
                    },
                    {
                        "tag": "input",
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "请输入供应商"
                        },
                        "value": {
                            "key": "supplier"
                        }
                    },
                    # 快递信息
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "**快递信息**"
                        }
                    },
                    {
                        "tag": "input",
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "请输入快递单号"
                        },
                        "value": {
                            "key": "tracking",
                            "text": tracking_info["tracking"] if tracking_info else ""
                        },
                        "disabled": True if tracking_info else False
                    },
                    {
                        "tag": "input",
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "请输入快递手机号"
                        },
                        "value": {
                            "key": "phone",
                            "text": tracking_info["phone"] if tracking_info else ""
                        },
                        "disabled": True if tracking_info else False
                    },
                    # 按钮组
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "提交并完成入库"
                                },
                                "type": "primary",
                                "value": {
                                    "tag": "submit",
                                    "form_type": "inbound",
                                    "batch_complete": True
                                }
                            },
                            {
                                "tag": "button",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "提交并继续入库"
                                },
                                "type": "default",
                                "value": {
                                    "tag": "submit",
                                    "form_type": "inbound",
                                    "batch_complete": False
                                }
                            }
                        ]
                    }
                ]
            }
            
            return card
            
        except Exception as e:
            logger.error(f"生成入库表单失败: {e}")
            return None

    async def handle_bot_menu_event(self, event_data: dict) -> None:
        """处理机器人菜单事件（异步方法）"""
        try:
            # 获取事件信息
            event_key = event_data.get('event', {}).get('event_key', '')
            operator = event_data.get('event', {}).get('operator', {})
            operator_id = operator.get('operator_id', {}).get('open_id')

            if not operator_id:
                logger.error("无法获取操作者ID")
                return

            # 根据菜单key处理不同的操作
            if event_key == 'inbound':
                # 生成入库表单卡片
                card = self.generate_inbound_form()
                if card:
                    # 发送卡片消息
                    if await self.send_card_message(
                        receive_id=operator_id,
                        card_content=card
                    ):
                        logger.info("Inbound form card sent successfully")
                    else:
                        logger.error("Failed to send inbound form card")
                        return
                else:
                    # 发送错误消息
                    if await self.send_text_message(
                        receive_id=operator_id,
                        content="❌ 生成入库表单失败，请稍后重试"
                    ):
                        logger.info("Error message sent successfully")
                    else:
                        logger.error("Failed to send error message")
                        return
            
            elif event_key == 'outbound':
                # TODO: 处理出库操作
                pass
            
            # ... 其他菜单项的处理 ...

        except Exception as e:
            logger.error(f"处理菜单事件失败: {e}")
            if operator_id:
                await self.send_text_message(
                    receive_id=operator_id,
                    content="❌ 操作失败，请稍后重试"
                )

    async def handle_card_action(self, form_data: dict) -> None:
        """处理卡片操作事件（异步方法）"""
        try:
            # 获取操作者信息
            operator_id = form_data.get('operator_id')
            raw_data = form_data.get('raw_data', {})
            action = raw_data.get('event', {}).get('action', {})
            
            # 只处理提交按钮的点击事件
            if action.get('tag') == 'button':
                form_values = action.get('value', {})
                if form_values.get('submit'):
                    form_type = form_values.get('form_type')
                    
                    if form_type == 'inbound':
                        # 处理入库表单
                        await self._handle_inbound_form(operator_id, form_values)
                    elif form_type == 'outbound':
                        # 处理出库表单
                        await self._handle_outbound_form(operator_id, form_values)
                    
        except Exception as e:
            logger.error(f"处理卡片操作失败: {e}")

    async def _handle_inbound_form(self, operator_id: str, form_values: dict) -> None:
        """处理入库表单数据（异步方法）"""
        try:
            # TODO: 处理入库逻辑
            logger.info(f"收到入库表单数据: {form_values}")
            
        except Exception as e:
            logger.error(f"处理入库表单失败: {e}")

    async def _handle_outbound_form(self, operator_id: str, form_values: dict) -> None:
        """处理出库表单数据（异步方法）"""
        try:
            # TODO: 处理出库逻辑
            logger.info(f"收到出库表单数据: {form_values}")
            
        except Exception as e:
            logger.error(f"处理出库表单失败: {e}")

    async def send_card_message(self, receive_id: str, card_content: dict) -> bool:
        """发送卡片消息（异步方法）"""
        try:
            logger.info("Attempting to send card message")
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

            # 使用 builder 模式构建请求体
            request_body = CreateMessageRequestBody.builder() \
                .receive_id(receive_id) \
                .msg_type("interactive") \
                .content(json.dumps(card_content, ensure_ascii=False)) \
                .build()

            # 构建完整请求
            request = CreateMessageRequest.builder() \
                .receive_id_type("open_id") \
                .request_body(request_body) \
                .build()

            logger.info("Sending card message...")
            response = self.client.im.v1.message.create(request)
            
            # 详细记录响应信息
            if not response.success():
                logger.error(
                    f"Send card message failed, code: {response.code}, "
                    f"msg: {response.msg}, "
                    f"log_id: {response.get_log_id()}"
                )
                return False
            
            logger.info("Card message sent successfully")
            return True

        except Exception as e:
            logger.error("Error sending card message: %s", str(e), exc_info=True)
            return False

    async def send_text_message(self, receive_id: str, content: str) -> bool:
        """发送文本消息（异步方法）"""
        try:
            return await self.send_message(receive_id, content, chat_type="p2p")
        except Exception as e:
            logger.error(f"发送文本消息失败: {e}", exc_info=True)
            return False

    async def send_message(self, receive_id: str, content: str, chat_type: str = "p2p") -> bool:
        """发送消息（异步方法）"""
        try:
            logger.info("Attempting to send message to %s: %s", chat_type, receive_id)
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

            # 根据消息类型设置 receive_id_type
            receive_id_type = "open_id" if chat_type == "p2p" else "chat_id"

            # 使用 builder 模式构建请求体
            request_body = CreateMessageRequestBody.builder() \
                .receive_id(receive_id) \
                .msg_type("text") \
                .content(json.dumps({"text": content}, ensure_ascii=False)) \
                .build()

            # 构建完整请求
            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
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

    async def handle_p2p_message(self, msg_data: dict) -> None:
        """处理点对点消息（异步方法）"""
        try:
            # 获取消息内容和发送者信息
            event = msg_data.get("event", {})
            sender_id = event.get("sender", {}).get("sender_id", {}).get("open_id")
            message = event.get("message", {})
            msg_content = message.get("content", "")
            
            if not sender_id:
                logger.error("无法获取发送者ID")
                return

            # 获取该用户的锁
            async with self.user_locks[sender_id]:
                # 如果消息内容是JSON字符串，解析它
                try:
                    content_json = json.loads(msg_content)
                    msg_text = content_json.get("text", "")
                except json.JSONDecodeError:
                    msg_text = msg_content

                logger.info(f"处理用户 {sender_id} 的消息: {msg_text[:100]}...")

                # 使用 DeepSeek 处理消息，传入 user_id
                response = await self.deepseek.chat(msg_text, user_id=sender_id)
                
                # 发送回复
                await self.send_text_message(
                    receive_id=sender_id,
                    content=response
                )
                
                logger.info(f"已完成处理用户 {sender_id} 的消息")
            
        except Exception as e:
            logger.error(f"处理p2p消息失败: {e}", exc_info=True)

    async def send_interactive_message(self, receive_id: str, content: str, chat_type: str = "p2p") -> bool:
        """发送交互式消息（异步方法）"""
        try:
            logger.info("Attempting to send interactive message to %s: %s", chat_type, receive_id)
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

            # 根据消息类型设置 receive_id_type
            receive_id_type = "open_id" if chat_type == "p2p" else "chat_id"

            # 使用 builder 模式构建请求体
            request_body = CreateMessageRequestBody.builder() \
                .receive_id(receive_id) \
                .msg_type("interactive") \
                .content(content) \
                .build()

            # 构建完整请求
            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(request_body) \
                .build()

            logger.info("Sending interactive request...")
            response = self.client.im.v1.message.create(request)
            
            # 详细记录响应信息
            if not response.success():
                logger.error(
                    f"Send interactive message failed, code: {response.code}, "
                    f"msg: {response.msg}, "
                    f"log_id: {response.get_log_id()}"
                )
                return False
            
            logger.info("Interactive message sent successfully")
            return True

        except Exception as e:
            logger.error("Error sending interactive message: %s", str(e), exc_info=True)
            return False

    async def update_card_message(self, message_id: str, card_content: dict) -> bool:
        """更新卡片消息（异步方法）"""
        try:
            logger.info("Attempting to update card message")
            from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

            # 构建请求体
            request_body = PatchMessageRequestBody.builder() \
                .content(json.dumps(card_content, ensure_ascii=False)) \
                .build()

            # 构建完整请求
            request = PatchMessageRequest.builder() \
                .message_id(message_id) \
                .request_body(request_body) \
                .build()

            logger.info("Updating card message...")
            response = self.client.im.v1.message.patch(request)
            
            if not response.success():
                logger.error(
                    f"Update card message failed, code: {response.code}, "
                    f"msg: {response.msg}, "
                    f"log_id: {response.get_log_id()}"
                )
                return False
            
            logger.info("Card message updated successfully")
            return True

        except Exception as e:
            logger.error("Error updating card message: %s", str(e), exc_info=True)
            return False

    def generate_disabled_inbound_form(self, warehouse_data: dict, product_data: dict, 
                                     quantity: float, price: float, supplier: str, tracking: str, phone: str) -> dict:
        """生成已禁用的入库表单卡片"""
        try:
            card = {
                "schema": "2.0",
                "config": {
                    "update_multi": True
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "入库表单 (已提交)"
                    },
                    "template": "grey",
                },
                "body": {
                    "direction": "vertical",
                    "padding": "12px 12px 12px 12px",
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": f"**📦 入库信息**\n\n" + 
                                         f"**商品：**{product_data.get('product_name')} ({product_data.get('product_spec')})\n" +
                                         f"**数量：**{quantity}\n" +
                                         f"**单价：**{price}\n" +
                                         f"**仓库：**{warehouse_data.get('warehouse')} - {warehouse_data.get('warehouse_note')}\n" +
                                         f"**供应商：**{supplier}\n\n" +
                                         "_✅ 此入库信息已成功提交_"
                            }
                        }
                    ]
                }
            }
            
            return card
            
        except Exception as e:
            logger.error(f"生成已禁用入库表单失败: {e}")
            return None

if __name__ == "__main__":
    processor = MessageProcessor(
        app_id=FEISHU_CONFIG["APP_ID"],
        app_secret=FEISHU_CONFIG["APP_SECRET"], 
        message_dir=Path("messages")
    )
    try:
        asyncio.run(processor.run())
    except Exception as e:
        logger.error(f"消息处理器运行失败: {e}")
    finally:
        processor.stop()
