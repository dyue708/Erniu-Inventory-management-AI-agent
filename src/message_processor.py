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
from typing import Optional, Dict, Any
import traceback
import aiohttp

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
                            # 处理卡片操作
                            if message.get("type") == "card_action":
                                print("开始处理卡片操作...")  # 调试日志
                                
                                data = message.get("data", {})
                                print(f"原始数据: {data}")  # 打印完整的原始数据
                                
                                # 解析 raw_data 获取 message_id
                                raw_data = json.loads(data.get("raw_data", "{}"))
                                message_id = raw_data.get("event", {}).get("context", {}).get("open_message_id")
                                
                                # 获取操作者ID
                                operator_id = data.get("operator_id")
                                
                                # 获取操作值
                                action_value = data.get("action_value", {})
                                
                                print(f"操作者ID: {operator_id}")  # 调试日志
                                print(f"消息ID: {message_id}")  # 调试日志
                                print(f"操作值: {action_value}")  # 调试日志
                                
                                if isinstance(action_value, str):
                                    try:
                                        action_value = json.loads(action_value)
                                    except:
                                        action_value = {}
                                
                                if action_value.get("action") == "add_product":
                                    try:
                                        # 获取当前行数
                                        current_rows = action_value.get("rows", 1)
                                        inbound_id = action_value.get("inbound_id")
                                        
                                        # 生成新的表单
                                        new_card = self.generate_inbound_form(
                                            tracking_info={'inbound_id': inbound_id} if inbound_id else None,
                                            product_rows=current_rows
                                        )
                                        
                                        if new_card and message_id:
                                            # 更新卡片
                                            logger.info(f"Updating card message: {message_id} with {current_rows} rows")
                                            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/patch"
                                            
                                            # 获取访问令牌
                                            tenant_access_token = await self.get_tenant_access_token()
                                            
                                            headers = {
                                                "Authorization": f"Bearer {tenant_access_token}",
                                                "Content-Type": "application/json; charset=utf-8",
                                            }
                                            
                                            update_data = {
                                                "content": json.dumps(new_card)
                                            }
                                            
                                            async with aiohttp.ClientSession() as session:
                                                async with session.patch(url, headers=headers, json=update_data) as response:
                                                    result = await response.json()
                                                    if result.get("code") == 0:
                                                        logger.info("Card updated successfully")
                                                    else:
                                                        logger.error(f"Failed to update card: {result}")
                                        else:
                                            logger.error(f"Invalid card update parameters: message_id={message_id}, rows={current_rows}")
                                            
                                    except Exception as e:
                                        logger.error(f"处理添加商品操作失败: {e}", exc_info=True)
                                        if operator_id:
                                            await self.send_text_message(
                                                receive_id=operator_id,
                                                content=f"❌ 添加商品失败: {str(e)}\n请重试或联系管理员"
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

    def generate_inbound_form(self, tracking_info=None, product_rows=1) -> dict:
        """生成入库表单卡片"""
        try:
            # 获取商品列表
            product_df = self.product_mgr.get_data()
            logger.debug(f"Product DataFrame columns: {product_df.columns.tolist()}")
            logger.debug(f"First product row: {product_df.iloc[0].to_dict()}")
            
            product_options = []
            for _, row in product_df.iterrows():
                product_options.append({
                    "text": {
                        "tag": "plain_text",
                        "content": f"{row['商品名称']} {row['商品规格']}"
                    },
                    "value": json.dumps({
                        "product_id": row['商品ID'],
                        "product_name": row['商品名称'],
                        "product_spec": row['商品规格']
                    }, ensure_ascii=False)
                })

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

            # 构建卡片
            card = {
                "schema": "2.0",
                "config": {
                    "update_multi": True
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "入库表单"
                    },
                    "template": "blue"
                },
                "body": {
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": "入库信息"
                            }
                        },
                        {
                            "tag": "column_set",
                            "columns": [
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [
                                        {
                                            "tag": "date_picker",
                                            "placeholder": {
                                                "tag": "plain_text",
                                                "content": "请选择入库日期"
                                            },
                                            "value": {
                                                "key": "date"
                                            }
                                        }
                                    ]
                                },
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [
                                        {
                                            "tag": "select_static",
                                            "placeholder": {
                                                "tag": "plain_text",
                                                "content": "仓库"
                                            },
                                            "options": warehouse_options,
                                            "value": {
                                                "key": "warehouse"
                                            }
                                        }
                                    ]
                                }
                            ]
                        },
                        {
                            "tag": "hr"
                        },
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": "供应商信息"
                            }
                        },
                        {
                            "tag": "input",
                            "placeholder": {
                                "tag": "plain_text",
                                "content": "供应商"
                            },
                            "value": {
                                "key": "supplier"
                            }
                        },
                        {
                            "tag": "hr"
                        },
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": "商品信息"
                            }
                        },
                        {
                            "tag": "div",
                            "fields": [
                                {
                                    "is_short": True,
                                    "text": {
                                        "tag": "lark_md",
                                        "content": "**商品名称**"
                                    }
                                },
                                {
                                    "is_short": True,
                                    "text": {
                                        "tag": "lark_md",
                                        "content": "**数量**"
                                    }
                                },
                                {
                                    "is_short": True,
                                    "text": {
                                        "tag": "lark_md",
                                        "content": "**单价**"
                                    }
                                }
                            ]
                        }
                    ] + [
                        {
                            "tag": "column_set",
                            "columns": [
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [
                                        {
                                            "tag": "select_static",
                                            "placeholder": {
                                                "tag": "plain_text",
                                                "content": "请选择商品"
                                            },
                                            "options": product_options,
                                            "value": {
                                                "key": f"product_{i}"
                                            }
                                        }
                                    ]
                                },
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [
                                        {
                                            "tag": "input",
                                            "placeholder": {
                                                "tag": "plain_text",
                                                "content": "请输入数量"
                                            },
                                            "value": {
                                                "key": f"quantity_{i}"
                                            }
                                        }
                                    ]
                                },
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [
                                        {
                                            "tag": "input",
                                            "placeholder": {
                                                "tag": "plain_text",
                                                "content": "请输入单价"
                                            },
                                            "value": {
                                                "key": f"price_{i}"
                                            }
                                        }
                                    ]
                                }
                            ]
                        } for i in range(product_rows)
                    ] + [
                        {
                            "tag": "column_set",
                            "columns": [
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [
                                        {
                                            "tag": "button",
                                            "text": {
                                                "tag": "plain_text",
                                                "content": "完成入库"
                                            },
                                            "type": "primary",
                                            "value": {
                                                "action": "complete_inbound",
                                                "inbound_id": tracking_info.get('inbound_id') if tracking_info else None
                                            }
                                        }
                                    ]
                                },
                                {
                                    "tag": "column",
                                    "width": "weighted",
                                    "weight": 1,
                                    "elements": [
                                        {
                                            "tag": "button",
                                            "text": {
                                                "tag": "plain_text",
                                                "content": "添加商品"
                                            },
                                            "type": "default",
                                            "value": {
                                                "action": "add_product",
                                                "rows": product_rows + 1,
                                                "inbound_id": tracking_info.get('inbound_id') if tracking_info else None
                                            }
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            }
            
            return card
            
        except Exception as e:
            logger.error(f"生成入库表单失败: {e}", exc_info=True)
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
            
            # 打印调试信息
            logger.info(f"Received card action: {json.dumps(action, ensure_ascii=False)}")
            
            # 检查是否是按钮点击事件
            if action.get('tag') == 'button':
                # 获取按钮的值
                value = action.get('value', {})
                logger.info(f"Button value: {json.dumps(value, ensure_ascii=False)}")
                
                # 获取表单数据
                form_data = raw_data.get('event', {}).get('action', {}).get('form_data', {})
                logger.info(f"Form data: {json.dumps(form_data, ensure_ascii=False)}")
                
                # 检查表单类型
                if value.get('form_type') == 'inbound':
                    # 构造完整的表单值
                    form_values = {
                        'form_data': form_data,
                        'batch_complete': value.get('batch_complete', True),
                        'message_id': raw_data.get('event', {}).get('message_id')  # 添加消息ID
                    }
                    
                    # 处理入库表单
                    await self._handle_inbound_form(operator_id, form_values)
                elif value.get('form_type') == 'outbound':
                    # 处理出库表单
                    await self._handle_outbound_form(operator_id, form_values)
                
        except Exception as e:
            logger.error(f"处理卡片操作失败: {e}", exc_info=True)
            if operator_id:
                await self.send_text_message(
                    receive_id=operator_id,
                    content=f"❌ 处理表单失败: {str(e)}\n请重试或联系管理员"
                )

    async def _handle_inbound_form(self, operator_id: str, form_values: dict) -> None:
        """处理入库表单数据（异步方法）"""
        try:
            # 获取消息ID
            raw_data = json.loads(form_values.get('raw_data', '{}'))
            message_id = raw_data.get('event', {}).get('context', {}).get('open_message_id')
            
            action_value = raw_data.get('event', {}).get('action', {}).get('value', {})
            action = action_value.get('action', '')
            
            if action == 'add_product':
                # 获取当前行数
                current_rows = action_value.get('rows', 1)
                inbound_id = action_value.get('inbound_id')
                
                # 生成新的表单，增加一行商品
                new_card = self.generate_inbound_form(
                    tracking_info={'inbound_id': inbound_id} if inbound_id else None,
                    product_rows=current_rows
                )
                
                if new_card and message_id:
                    # 更新当前卡片
                    logger.info(f"Updating card message: {message_id} with {current_rows} rows")
                    success = await self.update_card_message(message_id, new_card)
                    if not success:
                        logger.error("Failed to update card message")
                else:
                    logger.error(f"Invalid card update parameters: message_id={message_id}, rows={current_rows}")
                    
            elif action == 'complete_inbound':
                # 处理表单提交
                # ... 其他代码保持不变 ...
                pass
                
        except Exception as e:
            logger.error(f"处理入库表单失败: {str(e)}", exc_info=True)
            await self.send_text_message(
                receive_id=operator_id,
                content=f"❌ 入库提交失败: {str(e)}\n请重试或联系管理员"
            )

    def generate_disabled_inbound_form(self, warehouse_data: dict, product_data: dict, 
                                     quantity: float, price: float, supplier: str, 
                                     tracking: str, phone: str, inbound_id: str) -> dict:
        """生成已禁用的入库表单卡片"""
        try:
            total_price = quantity * price
            card = {
                "schema": "2.0",
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "入库表单 (已提交)"
                    },
                    "template": "grey",
                },
                "body": {
                    "direction": "vertical",
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": (
                                    f"**📦 入库信息**\n\n"
                                    f"**入库单号：**{inbound_id}\n"
                                    f"**商品：**{product_data.get('product_name')} ({product_data.get('product_spec', '')})\n"
                                    f"**数量：**{quantity}\n"
                                    f"**单价：**¥{price:.2f}\n"
                                    f"**总价：**¥{total_price:.2f}\n"
                                    f"**仓库：**{warehouse_data.get('warehouse')} - {warehouse_data.get('warehouse_note')}\n"
                                    f"**供应商：**{supplier}\n"
                                    f"**快递单号：**{tracking}\n"
                                    f"**快递手机：**{phone}\n\n"
                                    f"_✅ 此入库信息已成功提交_"
                                )
                            }
                        }
                    ]
                }
            }
            
            return card
            
        except Exception as e:
            logger.error(f"生成已禁用入库表单失败: {e}")
            return None

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

    async def update_card_message(self, message_id: str, card: dict) -> bool:
        """更新卡片消息
        Args:
            message_id: 消息ID
            card: 新的卡片内容
        Returns:
            bool: 是否更新成功
        """
        try:
            # 调用飞书 API 更新卡片
            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/patch"
            headers = {
                "Authorization": f"Bearer {self.tenant_access_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            
            data = {
                "content": json.dumps(card)
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=data) as response:
                    result = await response.json()
                    if result.get("code") == 0:
                        logger.info(f"Successfully updated card message: {message_id}")
                        return True
                    else:
                        logger.error(f"Failed to update card message: {result}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error updating card message: {e}")
            return False

    def _process_card_action(self, message_data: Dict[str, Any]) -> bool:
        """处理卡片操作消息"""
        try:
            print("\n开始处理卡片操作...")  # 调试日志
            print(f"接收到的消息数据: {json.dumps(message_data, ensure_ascii=False, indent=2)}")  # 调试日志
            
            data = message_data['data']
            form_data = data['form_data']
            operator_id = data['operator_id']
            current_time = int(datetime.now().timestamp())  # 秒级时间戳，不是毫秒
            
            print("解析表单数据...")  # 调试日志
            # 解析表单数据
            product = json.loads(form_data['product'])
            warehouse = json.loads(form_data['warehouse'])
            quantity = float(form_data['quantity'])
            price = float(form_data['price'])
            supplier = form_data.get('supplier', '')
            tracking = form_data.get('tracking', '')
            phone = form_data.get('phone', '')
            
            print(f"解析后的数据:\n产品: {product}\n仓库: {warehouse}\n数量: {quantity}\n价格: {price}")  # 调试日志
            
            # 构造入库数据
            inbound_data = [{
                "fields": {
                    "入库日期": current_time,  # 秒级时间戳
                    "快递单号": tracking,
                    "快递手机号": phone,
                    "供应商": supplier,
                    "商品ID": product.get("product_id"),
                    "商品名称": product.get("product_name"),
                    "入库数量": float(quantity),  # 确保是数字类型
                    "入库单价": float(price),    # 确保是数字类型
                    "入库总价": float(quantity) * float(price),  # 添加入库总价
                    "仓库名": warehouse.get("warehouse"),
                    "仓库备注": warehouse.get("warehouse_note"),
                    "仓库地址": warehouse.get("warehouse_address"),
                    "操作者ID": [{"id": operator_id}],
                    "操作时间": current_time  # 秒级时间戳
                }
            }]

            print(f"构造的入库数据: {json.dumps(inbound_data, ensure_ascii=False, indent=2)}")  # 调试日志

            # 使用入库管理器处理入库
            print("开始写入入库表...")  # 调试日志
            inbound_mgr = InboundManager()
            if inbound_mgr.add_inbound(inbound_data):
                print("入库数据写入成功")  # 调试日志
                # 发送确认消息
                confirmation_message = (
                    f"入库信息已收集完整，我已记录。\n"
                    f"入库商品明细:\n"
                    f"1. {product['product_name']} {product.get('product_spec', '')} "
                    f"-- 数量: {quantity} 单价: {price}  {warehouse['warehouse']}\n"
                    f"✔数据已成功写入入库表。"
                )
                
                self._send_message(operator_id, confirmation_message)
                return True
            else:
                print("入库数据写入失败")  # 调试日志
                raise Exception("入库处理失败")
            
        except Exception as e:
            print(f"处理卡片操作时出错: {str(e)}")  # 调试日志
            # 发送错误消息给用户
            if 'operator_id' in locals():
                self._send_message(operator_id, f"❌ 处理入库信息时出错: {str(e)}\n请联系管理员。")
            return False

    async def get_tenant_access_token(self) -> str:
        """获取租户访问令牌"""
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            headers = {
                "Content-Type": "application/json; charset=utf-8"
            }
            data = {
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    result = await response.json()
                    if result.get("code") == 0:
                        return result.get("tenant_access_token")
                    else:
                        logger.error(f"Failed to get tenant access token: {result}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error getting tenant access token: {e}")
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
