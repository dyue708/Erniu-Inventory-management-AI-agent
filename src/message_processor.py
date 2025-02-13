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
from table_manage import (
    WarehouseManager, 
    ProductManager, 
    InboundManager, 
    OutboundManager,
    InventorySummaryManager
)
from asyncio import Lock
from collections import defaultdict
from lark_oapi.api.im.v1 import *
from typing import Optional, Dict, Any
import traceback
import aiohttp
import pandas as pd

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
        self.sleep_interval = 0.1  # 无消息时的休眠时间（秒）
        
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
                            
                            # 处理不同类型的消息
                            message_type = message.get("type")
                            
                            if message_type == "card_action":
                                print("开始处理卡片操作...")  # 调试日志
                                data = message.get("data", {})
                                action_value = data.get("action_value", {})
                                
                                if isinstance(action_value, str):
                                    action_value = json.loads(action_value)
                                
                                # 从 raw_data 中获取 message_id
                                raw_data = json.loads(data.get("raw_data", "{}"))
                                message_id = raw_data.get("event", {}).get("context", {}).get("open_message_id")
                                
                                if action_value.get("action") == "add_product" and action_value.get("form_type") == "inbound":
                                    try:
                                        # 获取当前行数
                                        current_rows = action_value.get("rows", 3)
                                        inbound_id = action_value.get("inbound_id")
                                        
                                        # 生成新的表单
                                        new_card = self.generate_inbound_form(
                                            inbound_id=inbound_id,
                                            product_rows=current_rows
                                        )
                                        
                                        if new_card and message_id:
                                            # 使用 SDK 更新卡片
                                            logger.info(f"Updating card message: {message_id} with {current_rows} rows")
                                            
                                            # 构造请求对象
                                            request = PatchMessageRequest.builder() \
                                                .message_id(message_id) \
                                                .request_body(PatchMessageRequestBody.builder()
                                                    .content(json.dumps(new_card, ensure_ascii=False))
                                                    .build()) \
                                                .build()

                                            # 发起请求
                                            response = self.client.im.v1.message.patch(request)

                                            # 检查响应
                                            if response.success():
                                                logger.info("Card updated successfully")
                                                # 删除消息文件
                                                try:
                                                    os.remove(msg_file)
                                                    self.processed_files.add(msg_file)
                                                    logger.info(f"Successfully processed and removed file: {msg_file}")
                                                except Exception as e:
                                                    logger.error(f"Error removing message file: {e}")
                                            else:
                                                logger.error(
                                                    f"Failed to update card: code={response.code}, "
                                                    f"msg={response.msg}, log_id={response.get_log_id()}"
                                                )
                                        else:
                                            logger.error(f"Invalid card update parameters: message_id={message_id}, rows={current_rows}")
                                            
                                    except Exception as e:
                                        logger.error(f"处理添加商品操作失败: {e}", exc_info=True)
                                        operator_id = data.get("operator_id")
                                        if operator_id:
                                            await self.send_text_message(
                                                receive_id=operator_id,
                                                content=f"❌ 添加商品失败: {str(e)}\n请重试或联系管理员"
                                            )
                                elif action_value.get("action") == "add_product" and action_value.get("form_type") == "outbound":
                                    try:
                                        # 详细记录接收到的数据
                                        logger.info(f"Received outbound add_product action with data: {json.dumps(action_value, indent=2)}")
                                        
                                        # 获取当前行数
                                        current_rows = action_value.get("rows", 3)
                                        outbound_id = action_value.get("outbound_id")
                                        
                                        if not outbound_id:
                                            raise ValueError("Missing outbound_id in action_value")
                                            
                                        logger.info(f"Generating outbound form with {current_rows} rows for outbound_id: {outbound_id}")
                                        
                                        # 生成新的表单
                                        new_card = self.generate_outbound_form(
                                            outbound_id=outbound_id,
                                            product_rows=current_rows
                                        )
                                        
                                        if not new_card:
                                            raise ValueError("Failed to generate outbound form card")
                                            
                                        if not message_id:
                                            raise ValueError("Missing message_id")
                                            
                                        logger.info(f"Updating card message {message_id} with new form")
                                        
                                        # 构造请求对象
                                        request = PatchMessageRequest.builder() \
                                            .message_id(message_id) \
                                            .request_body(PatchMessageRequestBody.builder()
                                                .content(json.dumps(new_card, ensure_ascii=False))
                                                .build()) \
                                            .build()

                                        # 发起请求
                                        logger.info("Sending patch request to Feishu API")
                                        response = self.client.im.v1.message.patch(request)

                                        # 检查响应
                                        if response.success():
                                            logger.info("Card updated successfully")
                                            # 删除消息文件
                                            try:
                                                os.remove(msg_file)
                                                self.processed_files.add(msg_file)
                                                logger.info(f"Successfully processed and removed file: {msg_file}")
                                            except Exception as e:
                                                logger.error(f"Error removing message file: {e}", exc_info=True)
                                                # 继续执行，因为卡片更新已经成功
                                        else:
                                            error_msg = (
                                                f"Failed to update card: code={response.code}, "
                                                f"msg={response.msg}, log_id={response.get_log_id()}"
                                            )
                                            logger.error(error_msg)
                                            raise Exception(error_msg)
                                            
                                    except Exception as e:
                                        error_msg = f"处理添加商品操作失败: {str(e)}"
                                        logger.error(error_msg, exc_info=True)
                                        operator_id = data.get("operator_id")
                                        if operator_id:
                                            try:
                                                await self.send_text_message(
                                                    receive_id=operator_id,
                                                    content=f"❌ {error_msg}\n请重试或联系管理员"
                                                )
                                                logger.info(f"Error message sent to operator {operator_id}")
                                            except Exception as send_error:
                                                logger.error(f"Failed to send error message: {send_error}", exc_info=True)
                                elif action_value.get("action") == "submit" and action_value.get("form_type") == "outbound":
                                    try:
                                        # 收集所有商品数据
                                        form_data = data.get("form_data", {})
                                        outbound_id = action_value.get("outbound_id")
                                        operator_id = data.get("operator_id")
                                        current_time = int(datetime.now().timestamp() * 1000)
                                        
                                        outbound_records = []
                                        insufficient_stock = []
                                        i = 0
                                        
                                        while True:
                                            product_key = f"product_{i}"
                                            quantity_key = f"quantity_{i}"
                                            price_key = f"price_{i}"
                                            
                                            if product_key not in form_data:
                                                break
                                                
                                            product_id = form_data.get(product_key)
                                            quantity = float(form_data.get(quantity_key, 0))
                                            price = float(form_data.get(price_key, 0))
                                            
                                            if product_id and quantity > 0 and price > 0:
                                                # 获取商品详情
                                                product_df = self.product_mgr.get_data()
                                                product_info = product_df[product_df['商品ID'] == product_id].to_dict('records')
                                                
                                                if not product_info:
                                                    raise ValueError(f"商品ID无效: {product_id}")
                                                
                                                product_info = product_info[0]
                                                
                                                # 获取仓库信息
                                                warehouse_df = self.warehouse_mgr.get_data()
                                                warehouse_info = warehouse_df[warehouse_df['仓库名'] == form_data['warehouse']].to_dict('records')
                                                
                                                if not warehouse_info:
                                                    raise ValueError(f"仓库名无效: {form_data['warehouse']}")
                                                
                                                warehouse_info = warehouse_info[0]
                                                
                                                # 检查库存是否充足
                                                inventory_mgr = InventorySummaryManager()
                                                has_stock, current_stock = self._check_stock(
                                                    inventory_mgr,
                                                    product_id,
                                                    warehouse_info['仓库名'],
                                                    quantity
                                                )
                                                
                                                if not has_stock:
                                                    insufficient_stock.append({
                                                        'name': product_info['商品名称'],
                                                        'warehouse': warehouse_info['仓库名'],  # 添加仓库名
                                                        'required': quantity,
                                                        'current': current_stock
                                                    })
                                                    logger.warning(f"Insufficient stock for {product_info['商品名称']}: "
                                                                 f"required={quantity}, available={current_stock}")
                                                    break
                                                
                                                outbound_records.append({
                                                    "fields": {
                                                        "出库单号": outbound_id,
                                                        "出库日期": int(datetime.strptime(form_data['outbound_date'], "%Y-%m-%d %z").timestamp() * 1000),
                                                        "客户": form_data.get('customer', ''),
                                                        "仓库名": warehouse_info['仓库名'],
                                                        "仓库备注": warehouse_info.get('仓库备注', ''),
                                                        "仓库地址": warehouse_info.get('仓库地址', ''),
                                                        "商品ID": product_id,
                                                        "商品名称": product_info['商品名称'],
                                                        "商品规格": product_info.get('商品规格', ''),
                                                        "出库数量": quantity,
                                                        "出库单价": price,
                                                        "出库总价": quantity * price,
                                                        "操作者ID": [{"id": operator_id}],
                                                        "操作时间": current_time,
                                                        "快递单号": form_data.get('tracking', ''),
                                                        "快递手机号": form_data.get('phone', '')
                                                    }
                                                })
                                            i += 1
                                        
                                        if insufficient_stock:
                                            logger.info("Found insufficient stock, preparing error card...")
                                            # 生成库存不足提示卡片
                                            error_content = {
                                                "schema": "2.0",
                                                "config": {
                                                    "update_multi": True,
                                                    "wide_screen_mode": True
                                                },
                                                "body": {
                                                    "elements": [
                                                        {
                                                            "tag": "markdown",
                                                            "content": "❌ **库存不足**\n\n以下商品库存不足：\n\n" + "\n".join([
                                                                f"- **{item['name']}** | {item['warehouse']}\n  需求数量: {item['required']:.0f}\n  当前库存: {item['current']:.0f}"
                                                                for item in insufficient_stock
                                                            ]),
                                                            "text_align": "left"
                                                        }
                                                    ]
                                                },
                                                "header": {
                                                    "template": "red",
                                                    "title": {
                                                        "content": "库存不足提示",
                                                        "tag": "plain_text"
                                                    }
                                                }
                                            }
                                            
                                            logger.info(f"Updating message {message_id} with error card...")
                                            logger.info(f"Error content: {json.dumps(error_content, ensure_ascii=False)}")
                                            
                                            # 更新卡片
                                            try:
                                                # 构造请求对象
                                                request = PatchMessageRequest.builder() \
                                                    .message_id(message_id) \
                                                    .request_body(PatchMessageRequestBody.builder()
                                                        .content(json.dumps(error_content, ensure_ascii=False))
                                                        .build()) \
                                                    .build()
                                                
                                                # 发送请求
                                                logger.info("Sending patch request to update card...")
                                                response = self.client.im.v1.message.patch(request)
                                                
                                                # 检查响应
                                                if response.success():
                                                    logger.info("Successfully updated card with insufficient stock message")
                                                    logger.info(f"Successfully processed file: {msg_file}")
                                                else:
                                                    logger.error(
                                                        f"Failed to update error card: code={response.code}, "
                                                        f"msg={response.msg}, log_id={response.get_log_id()}"
                                                    )
                                            except Exception as e:
                                                logger.error(f"Error updating card with insufficient stock message: {e}", exc_info=True)
                                            finally:
                                                # 无论成功与否，都确保文件被标记为已处理并删除
                                                self.processed_files.add(msg_file)
                                                try:
                                                    os.remove(msg_file)
                                                    logger.info(f"Successfully removed file: {msg_file}")
                                                except Exception as e:
                                                    logger.error(f"Error removing message file: {e}")
                                                # 确保在库存不足时立即返回
                                                return True
                                            
                                        # 如果没有库存不足的情况，继续处理
                                        if not outbound_records:
                                            raise ValueError("没有有效的出库记录")
                                        
                                        # 写入出库记录
                                        outbound_mgr = OutboundManager()
                                        if outbound_mgr.add_outbound(outbound_records):
                                            try:
                                                # 获取出库明细记录
                                                outbound_details = outbound_mgr.get_outbound_details(outbound_id)

                                                # 按商品分组显示
                                                product_groups = {}
                                                for record in outbound_details:
                                                    fields = record["fields"]
                                                    product_id = fields["商品ID"]
                                                    if product_id not in product_groups:
                                                        product_groups[product_id] = []
                                                    product_groups[product_id].append(fields)

                                                logger.info("Product groups: %s", json.dumps(product_groups, indent=2, ensure_ascii=False))

                                                # 添加商品明细
                                                total_amount = 0
                                                total_profit = 0  # 添加总毛利变量
                                                details_content = ""

                                                # 遍历每个商品组
                                                for product_id, records in product_groups.items():
                                                    product_info = records[0]  # 获取第一条记录的商品信息
                                                    warehouse_name = product_info['仓库名']
                                                    details_content += f"\n**{product_info['商品名称']}** | {warehouse_name}\n"
                                                    
                                                    group_total_qty = sum(float(r['出库数量']) for r in records)
                                                    group_total_amount = sum(float(r['出库总价']) for r in records)
                                                    total_amount += group_total_amount
                                                    
                                                    # 计算该商品组的毛利
                                                    group_total_profit = sum(
                                                        (float(r['出库单价']) - float(r['入库单价'])) * float(r['出库数量'])
                                                        for r in records
                                                    )
                                                    total_profit += group_total_profit
                                                    
                                                    details_content += (
                                                        f"  总数量: {group_total_qty:.0f} | "
                                                        f"总金额: ¥{group_total_amount:.2f} | "
                                                        f"毛利: ¥{group_total_profit:.2f}\n"
                                                    )
                                                    
                                                    # 显示每条出库记录的详细信息
                                                    for record in records:
                                                        cost_price = float(record['入库单价'])
                                                        out_price = float(record['出库单价'])
                                                        out_qty = float(record['出库数量'])
                                                        profit = (out_price - cost_price) * out_qty
                                                        
                                                        details_content += (
                                                            f"    - 入库价: ¥{cost_price:.2f} | "
                                                            f"出库价: ¥{out_price:.2f} | "
                                                            f"出库数量: {out_qty:.0f} | "
                                                            f"毛利: ¥{profit:.2f}\n"
                                                        )

                                                # 生成成功消息卡片
                                                success_content = {
                                                    "schema": "2.0",
                                                    "config": {
                                                        "update_multi": True,
                                                        "style": {
                                                            "text_size": {
                                                                "normal_v2": {
                                                                    "default": "normal",
                                                                    "pc": "normal",
                                                                    "mobile": "heading"
                                                                }
                                                            }
                                                        }
                                                    },
                                                    "body": {
                                                        "elements": [
                                                            {
                                                                "tag": "markdown",
                                                                "content": f":OK: **出库单 {outbound_id} 处理成功**\n\n",
                                                                "text_align": "left",
                                                                "text_size": "normal_v2"
                                                            },
                                                            {
                                                                "tag": "markdown",
                                                                "content": "📦 **出库明细：**\n",
                                                                "text_align": "left",
                                                                "text_size": "normal_v2"
                                                            }
                                                        ]
                                                    }
                                                }
                                                
                                                success_content["body"]["elements"].append({
                                                    "tag": "markdown",
                                                    "content": details_content,
                                                    "text_align": "left",
                                                    "text_size": "normal_v2"
                                                })
                                                
                                                success_content["body"]["elements"].append({
                                                    "tag": "markdown",
                                                    "content": f"\n💰 **订单总计：** ¥{total_amount:.2f} | **总毛利：** ¥{total_profit:.2f}",
                                                    "text_align": "left",
                                                    "text_size": "normal_v2"
                                                })

                                                # 更新卡片
                                                request = PatchMessageRequest.builder() \
                                                    .message_id(message_id) \
                                                    .request_body(PatchMessageRequestBody.builder()
                                                        .content(json.dumps(success_content, ensure_ascii=False))
                                                        .build()) \
                                                    .build()

                                                response = self.client.im.v1.message.patch(request)
                                                
                                                if response.success():
                                                    logger.info("Success card updated successfully")
                                                    # 删除消息文件
                                                    try:
                                                        os.remove(msg_file)
                                                        self.processed_files.add(msg_file)
                                                        logger.info(f"Successfully processed and removed file: {msg_file}")
                                                    except Exception as e:
                                                        logger.error(f"Error removing message file: {e}")
                                                else:
                                                    logger.error(
                                                        f"Failed to update success card: code={response.code}, "
                                                        f"msg={response.msg}, log_id={response.get_log_id()}"
                                                    )
                                            except Exception as e:
                                                logger.error(f"Error updating inventory: {str(e)}", exc_info=True)
                                                raise
                                            finally:
                                                try:
                                                    os.remove(msg_file)
                                                    self.processed_files.add(msg_file)
                                                    logger.info(f"Successfully processed and removed file: {msg_file}")
                                                except Exception as e:
                                                    logger.error(f"Error removing message file: {e}")
                                                return True
                                        else:
                                            raise Exception("出库记录写入失败")
                                        
                                    except Exception as e:
                                        error_msg = f"❌ 出库失败: {str(e)}\n请重试或联系管理员"
                                        logger.error(f"Error processing outbound form: {str(e)}", exc_info=True)
                                        await self.send_text_message(
                                            receive_id=data.get('operator_id'),
                                            content=error_msg
                                        )
                                    finally:
                                        try:
                                            os.remove(msg_file)
                                            self.processed_files.add(msg_file)
                                            logger.info(f"Successfully processed and removed file: {msg_file}")
                                        except Exception as e:
                                            logger.error(f"Error removing message file: {e}")
                                        return True
                                elif action_value.get("action") == "submit" and action_value.get("form_type") == "inbound":
                                    try:
                                        # 收集所有商品数据
                                        form_data = data.get("form_data", {})
                                        inbound_id = action_value.get("inbound_id")
                                        operator_id = data.get("operator_id")
                                        current_time = int(datetime.now().timestamp() * 1000)
                                        
                                        inbound_records = []
                                        i = 0
                                        
                                        while True:
                                            product_key = f"product_{i}"
                                            quantity_key = f"quantity_{i}"
                                            price_key = f"price_{i}"
                                            
                                            if product_key not in form_data:
                                                break
                                                
                                            product_id = form_data.get(product_key)
                                            quantity = float(form_data.get(quantity_key, 0))
                                            price = float(form_data.get(price_key, 0))
                                            
                                            if product_id and quantity > 0 and price > 0:
                                                # 获取商品详情
                                                product_df = self.product_mgr.get_data()
                                                product_info = product_df[product_df['商品ID'] == product_id].to_dict('records')
                                                
                                                if not product_info:
                                                    raise ValueError(f"商品ID无效: {product_id}")
                                                
                                                product_info = product_info[0]
                                                
                                                # 获取仓库信息
                                                warehouse_df = self.warehouse_mgr.get_data()
                                                warehouse_info = warehouse_df[warehouse_df['仓库名'] == form_data['warehouse']].to_dict('records')
                                                
                                                if not warehouse_info:
                                                    raise ValueError(f"仓库名无效: {form_data['warehouse']}")
                                                
                                                warehouse_info = warehouse_info[0]
                                                
                                                inbound_records.append({
                                                    "fields": {
                                                        "入库单号": inbound_id,
                                                        "入库日期": int(datetime.strptime(form_data['inbound_date'], "%Y-%m-%d %z").timestamp() * 1000),
                                                        "供应商": form_data.get('supplier', ''),
                                                        "仓库名": warehouse_info['仓库名'],
                                                        "仓库备注": warehouse_info.get('仓库备注', ''),
                                                        "仓库地址": warehouse_info.get('仓库地址', ''),
                                                        "商品ID": product_id,
                                                        "商品名称": product_info['商品名称'],
                                                        "商品规格": product_info.get('商品规格', ''),
                                                        "入库数量": quantity,
                                                        "入库单价": price,
                                                        "入库总价": quantity * price,
                                                        "操作者ID": [{"id": operator_id}],
                                                        "操作时间": current_time,
                                                        "快递单号": form_data.get('tracking', ''),
                                                        "快递手机号": form_data.get('phone', '')
                                                    }
                                                })
                                            i += 1
                                        
                                        if not inbound_records:
                                            raise ValueError("没有有效的入库记录")
                                        
                                        # 写入入库记录
                                        inbound_mgr = InboundManager()
                                        if inbound_mgr.add_inbound(inbound_records):
                                            try:
                                                # 生成成功消息卡片
                                                success_content = {
                                                    "schema": "2.0",
                                                    "config": {
                                                        "update_multi": True,
                                                        "style": {
                                                            "text_size": {
                                                                "normal_v2": {
                                                                    "default": "normal",
                                                                    "pc": "normal",
                                                                    "mobile": "heading"
                                                                }
                                                            }
                                                        }
                                                    },
                                                    "body": {
                                                        "elements": [
                                                            {
                                                                "tag": "markdown",
                                                                "content": f":OK: **入库单 {inbound_id} 处理成功**\n\n",
                                                                "text_align": "left",
                                                                "text_size": "normal_v2"
                                                            },
                                                            {
                                                                "tag": "markdown",
                                                                "content": "📦 **入库明细：**\n",
                                                                "text_align": "left",
                                                                "text_size": "normal_v2"
                                                            }
                                                        ]
                                                    }
                                                }
                                                
                                                # 添加商品明细
                                                total_amount = 0
                                                details_content = ""
                                                for record in inbound_records:
                                                    fields = record["fields"]
                                                    total_amount += fields['入库总价']
                                                    details_content += (
                                                        f"- {fields['商品名称']} ({fields['商品规格']}) | {fields['仓库名']}\n"
                                                        f"  数量: {fields['入库数量']:.0f} | "
                                                        f"单价: ¥{fields['入库单价']:.2f} | "
                                                        f"小计: ¥{fields['入库总价']:.2f}\n"
                                                    )
                                                
                                                # 添加快递信息到成功消息
                                                if fields.get('tracking') or fields.get('phone'):
                                                    details_content += (
                                                        f"📬 **快递信息：**\n" + 
                                                        (f"- 快递单号：{fields['快递单号']}\n" if fields.get('tracking') else "") +
                                                        (f"- 收件手机：{fields['快递手机号']}\n" if fields.get('phone') else "")
                                                    )
                                                
                                                success_content["body"]["elements"].append({
                                                    "tag": "markdown",
                                                    "content": details_content,
                                                    "text_align": "left",
                                                    "text_size": "normal_v2"
                                                })
                                                
                                                success_content["body"]["elements"].append({
                                                    "tag": "markdown",
                                                    "content": f"\n💰 **总金额：** ¥{total_amount:.2f}",
                                                    "text_align": "left",
                                                    "text_size": "normal_v2"
                                                })
                                                
                                                # 更新卡片
                                                request = PatchMessageRequest.builder() \
                                                    .message_id(message_id) \
                                                    .request_body(PatchMessageRequestBody.builder()
                                                        .content(json.dumps(success_content, ensure_ascii=False))
                                                        .build()) \
                                                    .build()

                                                response = self.client.im.v1.message.patch(request)
                                                
                                                if response.success():
                                                    logger.info("Success card updated successfully")
                                                    # 删除消息文件并标记为已处理
                                                    try:
                                                        os.remove(msg_file)
                                                        self.processed_files.add(msg_file)
                                                        logger.info(f"Successfully processed and removed file: {msg_file}")
                                                    except Exception as e:
                                                        logger.error(f"Error removing message file: {e}")
                                                else:
                                                    logger.error(
                                                        f"Failed to update success card: code={response.code}, "
                                                        f"msg={response.msg}, log_id={response.get_log_id()}"
                                                    )
                                            except Exception as e:
                                                logger.error(f"Error updating inventory: {str(e)}", exc_info=True)
                                                raise
                                            finally:
                                                # 无论成功与否，都确保文件被标记为已处理
                                                self.processed_files.add(msg_file)
                                                return True
                                        else:
                                            raise ValueError("入库记录写入失败")
                                        
                                    except Exception as e:
                                        error_msg = f"❌ 入库失败: {str(e)}\n请重试或联系管理员"
                                        logger.error(f"Error processing inbound form: {str(e)}", exc_info=True)
                                        await self.send_text_message(
                                            receive_id=data.get('operator_id'),
                                            content=error_msg
                                        )
                                        # 确保在发生错误时也标记文件为已处理
                                        try:
                                            self.processed_files.add(msg_file)
                                            os.remove(msg_file)
                                        except Exception as e:
                                            logger.error(f"Error removing message file: {e}")
                                        return True
                            elif message_type in ["p2p_message", "message"]:
                                try:
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
                                            # 删除消息文件
                                            try:
                                                os.remove(msg_file)
                                                self.processed_files.add(msg_file)
                                                logger.info(f"Successfully processed and removed file: {msg_file}")
                                            except Exception as e:
                                                logger.error(f"Error removing message file: {e}")
                                        else:
                                            logger.error("Failed to send AI reply")
                                            continue  # 如果发送失败，跳过文件删除
                                    
                                except Exception as e:
                                    logger.error(f"Error processing message: {e}")
                                    continue
                            elif message_type == "bot_menu_event":
                                try:
                                    event_data = json.loads(message["data"])
                                    event = event_data["event"]
                                    receive_id = event["operator"]["operator_id"]["open_id"]
                                    
                                    if event.get("event_key") == "INBOUND":
                                        # 生成入库表单卡片
                                        card = self.generate_inbound_form()
                                        if card:
                                            # 发送卡片消息
                                            if await self.send_card_message(
                                                receive_id=receive_id,
                                                card_content=card
                                            ):
                                                logger.info("Inbound form card sent successfully")
                                                # 处理成功后删除消息文件
                                                try:
                                                    os.remove(msg_file)
                                                    self.processed_files.add(msg_file)
                                                    logger.info(f"Successfully processed and removed file: {msg_file}")
                                                except Exception as e:
                                                    logger.error(f"Error removing message file: {e}")
                                            else:
                                                logger.error("Failed to send inbound form card")
                                                continue  # 如果发送失败，跳过文件删除
                                        else:
                                            # 发送错误消息
                                            await self.send_text_message(
                                                receive_id=receive_id,
                                                content="❌ 生成入库表单失败，请稍后重试"
                                            )
                                            continue
                                            
                                    elif event.get("event_key") == "OUTBOUND":
                                        # 生成出库表单卡片
                                        card = self.generate_outbound_form()
                                        if card:
                                            # 发送卡片消息
                                            if await self.send_card_message(
                                                receive_id=receive_id,
                                                card_content=card
                                            ):
                                                logger.info("Outbound form card sent successfully")
                                                # 处理成功后删除消息文件
                                                try:
                                                    os.remove(msg_file)
                                                    self.processed_files.add(msg_file)
                                                    logger.info(f"Successfully processed and removed file: {msg_file}")
                                                except Exception as e:
                                                    logger.error(f"Error removing message file: {e}")
                                            else:
                                                logger.error("Failed to send outbound form card")
                                                continue  # 如果发送失败，跳过文件删除
                                        else:
                                            # 发送错误消息
                                            await self.send_text_message(
                                                receive_id=receive_id,
                                                content="❌ 生成出库表单失败，请稍后重试"
                                            )
                                            continue
                                            
                                except Exception as e:
                                    logger.error(f"Error processing bot menu event: {e}", exc_info=True)
                                    continue
                            
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

    def generate_inbound_form(self, inbound_id = None, product_rows=3) -> dict:
        try:
            # 获取当前日期
            current_date = datetime.now().strftime('%Y-%m-%d')
            if inbound_id is None:
                inbound_id = f"IN-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            # 获取仓库和商品选项
            warehouse_options = self.get_warehouse_options()
            product_options = self.get_product_options()
            
            # 构建卡片
            card = {
                "schema": "2.0",
                "config": {
                    "update_multi": True,
                    "style": {
                        "text_size": {
                            "normal_v2": {
                                "default": "normal",
                                "pc": "normal",
                                "mobile": "heading"
                            }
                        }
                    }
                },
                "body": {
                    "direction": "vertical",
                    "padding": "12px 12px 12px 12px",
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": "",
                                "text_size": "normal_v2",
                                "text_align": "left",
                                "text_color": "default"
                            },
                            "margin": "0px 0px 0px 0px"
                        },
                        {
                            "tag": "form",
                            "elements": [
                                {
                                    "tag": "div",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "入库信息",
                                        "text_size": "normal_v2",
                                        "text_align": "left",
                                        "text_color": "default"
                                    },
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "column_set",
                                    "horizontal_spacing": "8px",
                                    "horizontal_align": "left",
                                    "columns": [
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "date_picker",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请选择入库日期"
                                                    },
                                                    "width": "default",
                                                    "initial_date": current_date,
                                                    "name": "inbound_date",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        },
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "select_static",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请选择仓库"
                                                    },
                                                    "options": warehouse_options,
                                                    "type": "default",
                                                    "width": "default",
                                                    "name": "warehouse",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        }
                                    ],
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "hr",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "div",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "供应商信息",
                                        "text_size": "normal_v2",
                                        "text_align": "left",
                                        "text_color": "default"
                                    },
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "input",
                                    "placeholder": {
                                        "tag": "plain_text",
                                        "content": "请输入"
                                    },
                                    "default_value": "",
                                    "width": "default",
                                    "name": "supplier",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "hr",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "div",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "商品信息",
                                        "text_size": "normal_v2",
                                        "text_align": "left",
                                        "text_color": "default"
                                    },
                                    "margin": "0px 0px 0px 0px"
                                }
                            ] + [
                                {
                                    "tag": "column_set",
                                    "horizontal_spacing": "8px",
                                    "horizontal_align": "left",
                                    "columns": [
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "select_static",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请选择商品名"
                                                    },
                                                    "options": product_options,
                                                    "type": "default",
                                                    "width": "default",
                                                    "name": f"product_{i}",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        },
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "input",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请输入数量"
                                                    },
                                                    "default_value": "",
                                                    "width": "default",
                                                    "name": f"quantity_{i}",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        },
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "input",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请输入单价"
                                                    },
                                                    "default_value": "",
                                                    "width": "default",
                                                    "name": f"price_{i}",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        }
                                    ],
                                    "margin": "0px 0px 0px 0px"
                                } for i in range(product_rows)
                            ] + [ {
                                    "tag": "hr",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "div",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "物流信息",
                                        "text_size": "normal_v2",
                                        "text_align": "left",
                                        "text_color": "default"
                                    },
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "input",
                                    "placeholder": {
                                        "tag": "plain_text",
                                        "content": "请输入快递单号"
                                    },
                                    "default_value": "",
                                    "width": "default",
                                    "name": "tracking",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "input",
                                    "placeholder": {
                                        "tag": "plain_text",
                                        "content": "请输入收件人手机号"
                                    },
                                    "default_value": "",
                                    "width": "default",
                                    "name": "phone",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "hr",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "hr",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "column_set",
                                    "horizontal_align": "left",
                                    "columns": [
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "button",
                                                    "text": {
                                                        "tag": "plain_text",
                                                        "content": "完成入库"
                                                    },
                                                    "type": "primary",
                                                    "width": "default",
                                                    "behaviors": [
                                                        {
                                                            "type": "callback",
                                                            "value": {
                                                                "action": "submit",
                                                                "inbound_id": inbound_id,
                                                                "form_type": "inbound"
                                                            }
                                                        }
                                                    ],
                                                    "form_action_type": "submit",
                                                    "name": "submit"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        },
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "button",
                                                    "text": {
                                                        "tag": "plain_text",
                                                        "content": "添加商品"
                                                    },
                                                    "type": "default",
                                                    "width": "default",
                                                    "form_action_type": "submit",
                                                    "size": "medium",
                                                    "behaviors": [
                                                        {
                                                            "type": "callback",
                                                            "value": {
                                                                "action": "add_product",
                                                                "inbound_id": inbound_id,
                                                                "rows": product_rows + 1 ,
                                                                "form_type": "inbound"
                                                            }
                                                        }
                                                    ],
                                                    "name": "add_product",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        }
                                    ],
                                    "margin": "0px 0px 0px 0px"
                                }
                            ],
                            "direction": "vertical",
                            "padding": "4px 0px 4px 0px",
                            "margin": "0px 0px 0px 0px",
                            "name": "inbound_form"
                        }
                    ]
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"入库表单: {inbound_id}"
                    },
                    "subtitle": {
                        "tag": "plain_text",
                        "content": ""
                    },
                    "template": "blue",
                    "padding": "12px 12px 12px 12px"
                }
            }
            
            return card
            
        except Exception as e:
            logger.error(f"生成入库表单失败: {e}", exc_info=True)
            return None

    def generate_outbound_form(self, outbound_id = None, product_rows=3) -> dict:
        """生成出库表单卡片"""
        try:
            # 获取当前日期
            current_date = datetime.now().strftime('%Y-%m-%d')
            if outbound_id is None:
                outbound_id = f"OUT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            # 获取仓库和商品选项
            warehouse_options = self.get_warehouse_options()
            product_options = self.get_product_options()
            
            # 构建卡片
            card = {
                "schema": "2.0",
                "config": {
                    "update_multi": True,
                    "style": {
                        "text_size": {
                            "normal_v2": {
                                "default": "normal",
                                "pc": "normal",
                                "mobile": "heading"
                            }
                        }
                    }
                },
                "body": {
                    "direction": "vertical",
                    "padding": "12px 12px 12px 12px",
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": "",
                                "text_size": "normal_v2",
                                "text_align": "left",
                                "text_color": "default"
                            },
                            "margin": "0px 0px 0px 0px"
                        },
                        {
                            "tag": "form",
                            "elements": [
                                {
                                    "tag": "div",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "出库信息",
                                        "text_size": "normal_v2",
                                        "text_align": "left",
                                        "text_color": "default"
                                    },
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "column_set",
                                    "horizontal_spacing": "8px",
                                    "horizontal_align": "left",
                                    "columns": [
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "date_picker",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请选择出库日期"
                                                    },
                                                    "width": "default",
                                                    "initial_date": current_date,
                                                    "name": "outbound_date",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        },
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "select_static",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请选择仓库"
                                                    },
                                                    "options": warehouse_options,
                                                    "type": "default",
                                                    "width": "default",
                                                    "name": "warehouse",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        }
                                    ],
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "hr",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "div",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "客户信息",
                                        "text_size": "normal_v2",
                                        "text_align": "left",
                                        "text_color": "default"
                                    },
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "input",
                                    "placeholder": {
                                        "tag": "plain_text",
                                        "content": "请输入客户名称"
                                    },
                                    "default_value": "",
                                    "width": "default",
                                    "name": "customer",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "hr",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "div",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "商品信息",
                                        "text_size": "normal_v2",
                                        "text_align": "left",
                                        "text_color": "default"
                                    },
                                    "margin": "0px 0px 0px 0px"
                                }
                            ] + [
                                {
                                    "tag": "column_set",
                                    "horizontal_spacing": "8px",
                                    "horizontal_align": "left",
                                    "columns": [
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "select_static",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请选择商品名"
                                                    },
                                                    "options": product_options,
                                                    "type": "default",
                                                    "width": "default",
                                                    "name": f"product_{i}",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        },
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "input",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请输入数量"
                                                    },
                                                    "default_value": "",
                                                    "width": "default",
                                                    "name": f"quantity_{i}",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        },
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "input",
                                                    "placeholder": {
                                                        "tag": "plain_text",
                                                        "content": "请输入单价"
                                                    },
                                                    "default_value": "",
                                                    "width": "default",
                                                    "name": f"price_{i}",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        }
                                    ],
                                    "margin": "0px 0px 0px 0px"
                                } for i in range(product_rows)
                            ] + [
                                {
                                    "tag": "hr",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "div",
                                    "text": {
                                        "tag": "plain_text",
                                        "content": "物流信息",
                                        "text_size": "normal_v2",
                                        "text_align": "left",
                                        "text_color": "default"
                                    },
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "input",
                                    "placeholder": {
                                        "tag": "plain_text",
                                        "content": "请输入快递单号"
                                    },
                                    "default_value": "",
                                    "width": "default",
                                    "name": "tracking",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "input",
                                    "placeholder": {
                                        "tag": "plain_text",
                                        "content": "请输入收件人手机号"
                                    },
                                    "default_value": "",
                                    "width": "default",
                                    "name": "phone",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "hr",
                                    "margin": "0px 0px 0px 0px"
                                },
                                {
                                    "tag": "column_set",
                                    "horizontal_align": "left",
                                    "columns": [
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "button",
                                                    "text": {
                                                        "tag": "plain_text",
                                                        "content": "完成出库"
                                                    },
                                                    "type": "primary",
                                                    "width": "default",
                                                    "behaviors": [
                                                        {
                                                            "type": "callback",
                                                            "value": {
                                                                "action": "submit",
                                                                "outbound_id": outbound_id,
                                                                "form_type": "outbound"
                                                            }
                                                        }
                                                    ],
                                                    "form_action_type": "submit",
                                                    "name": "submit"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        },
                                        {
                                            "tag": "column",
                                            "width": "weighted",
                                            "elements": [
                                                {
                                                    "tag": "button",
                                                    "text": {
                                                        "tag": "plain_text",
                                                        "content": "添加商品"
                                                    },
                                                    "type": "default",
                                                    "width": "default",
                                                    "form_action_type": "submit",
                                                    "size": "medium",
                                                    "behaviors": [
                                                        {
                                                            "type": "callback",
                                                            "value": {
                                                                "action": "add_product",
                                                                "outbound_id": outbound_id,
                                                                "rows": product_rows + 1,
                                                                "form_type": "outbound"
                                                            }
                                                        }
                                                    ],
                                                    "name": "add_product",
                                                    "margin": "0px 0px 0px 0px"
                                                }
                                            ],
                                            "vertical_spacing": "8px",
                                            "horizontal_align": "left",
                                            "vertical_align": "top",
                                            "weight": 1
                                        }
                                    ],
                                    "margin": "0px 0px 0px 0px"
                                }
                            ],
                            "direction": "vertical",
                            "padding": "4px 0px 4px 0px",
                            "margin": "0px 0px 0px 0px",
                            "name": "outbound_form"
                        }
                    ]
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"出库表单: {outbound_id}"
                    },
                    "subtitle": {
                        "tag": "plain_text",
                        "content": ""
                    },
                    "template": "red",
                    "padding": "12px 12px 12px 12px"
                }
            }
            
            return card
            
        except Exception as e:
            logger.error(f"生成出库表单失败: {e}", exc_info=True)
            return None

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

    def get_warehouse_options(self) -> list:
        """获取仓库选项列表"""
        try:
            warehouse_df = self.warehouse_mgr.get_data()
            options = []
            for _, row in warehouse_df.iterrows():
                options.append({
                    "text": {
                        "tag": "plain_text",
                        "content": f"{row['仓库名']} - {row['仓库备注']}"
                    },
                    "value": row['仓库名']
                })
            return options
        except Exception as e:
            logger.error(f"获取仓库选项失败: {e}", exc_info=True)
            return []

    def get_product_options(self) -> list:
        """获取商品选项列表"""
        try:
            product_df = self.product_mgr.get_data()
            options = []
            for _, row in product_df.iterrows():
                options.append({
                    "text": {
                        "tag": "plain_text",
                        "content": f"{row['商品名称']} {row['商品规格']}"
                    },
                    "value": row['商品ID']
                })
            return options
        except Exception as e:
            logger.error(f"获取商品选项失败: {e}", exc_info=True)
            return []

    def _check_stock(self, inventory_mgr, product_id: str, warehouse: str, required_qty: float) -> tuple[bool, float]:
        """检查商品库存是否充足"""
        try:
            stock_df = inventory_mgr.get_stock_summary(
                product_id=product_id,
                warehouse=warehouse
            )
            
            if stock_df.empty:
                logger.warning(f"No stock record found for product {product_id} in warehouse {warehouse}")
                return False, 0
            
            # 确保数值转换
            stock_df['当前库存'] = pd.to_numeric(stock_df['当前库存'], errors='coerce')
            current_stock = float(stock_df['当前库存'].fillna(0).sum())
            
            logger.info(f"Stock check - Product: {product_id}, Warehouse: {warehouse}, "
                       f"Required: {required_qty}, Available: {current_stock}")
            
            return current_stock >= required_qty, current_stock
            
        except Exception as e:
            logger.error(f"Error checking stock: {e}", exc_info=True)
            return False, 0

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
