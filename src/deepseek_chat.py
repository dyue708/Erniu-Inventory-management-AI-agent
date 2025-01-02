import logging
from typing import List, Optional
import json
from config import DEEPSEEK_CONFIG, FEISHU_CONFIG
import asyncio
from feishu_sheet import FeishuSheet
import re
from datetime import datetime
from table_manage import InventoryManager, WarehouseManager
import pandas as pd
import httpx

# 配置日志记录器
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class DeepSeekChat:
    def __init__(self):
        self.api_key = DEEPSEEK_CONFIG["API_KEY"]
        self.api_base = DEEPSEEK_CONFIG["BASE_URL"]
        self.model = DEEPSEEK_CONFIG["MODEL"]
        
        # 获取仓库和商品信息
        self.warehouse_manager = WarehouseManager()
        self.warehouses = self._get_warehouses()
        
        # 修改系统提示词
        base_prompt = """你是一个出入库管理助手。你需要帮助收集完整的入库信息，并以JSON格式返回。

每次对话你都需要：
1. 分析用户输入，提取相关信息
2. 将信息格式化为JSON
3. 检查是否所有必要信息都已收集
4. 如果信息完整，返回完整的JSON；如果不完整，返回已收集的信息并友好询问缺失信息

必要的信息字段包括：
{
    "entry_date": "入库日期（YYYY-MM-DD格式，默认今天）",
    "tracking_number": "快递单号",
    "phone": "手机号",
    "platform": "采购平台",
    "warehouse": {
        "name": "仓库名",
        "category": "仓库分类",
        "address": "仓库地址"
    },
    "products": [
        {
            "name": "商品名称",
            "quantity": "数量",
            "price": "单价"
        }
    ]
}

请按以下格式返回数据：
1. 如果信息完整：
<JSON>
{完整的JSON数据}
</JSON>
入库信息已收集完整，我已记录。

2. 如果信息不完整：
<JSON>
{当前已收集的JSON数据}
</JSON>
请继续提供：[缺失的字段列表]"""
        
        # 在系统提示词中添加今日日期和可用仓库信息
        today = datetime.now().strftime("%Y-%m-%d")
        warehouse_info = self._format_warehouse_info()
        self.system_prompt = f"{base_prompt}\n\n今天是 {today}\n\n可用的仓库信息：\n{warehouse_info}"
        
        self.conversations = {}
        self.max_history = DEEPSEEK_CONFIG.get("MAX_HISTORY", 10)
        self.inventory_manager = InventoryManager()
        self.current_inventory_data = {}  # 存储当前收集的信息

    def _get_warehouses(self) -> pd.DataFrame:
        """获取仓库信息"""
        try:
            return self.warehouse_manager.get_data()
        except Exception as e:
            logger.error(f"获取仓库信息失败: {str(e)}")
            return pd.DataFrame()

    def _format_warehouse_info(self) -> str:
        """格式化仓库信息为字符串"""
        if self.warehouses.empty:
            return "暂无可用仓库信息"
        
        warehouse_str = ""
        for _, row in self.warehouses.iterrows():
            warehouse_str += (
                f"- 仓库名: {row['仓库名']}\n"
                f"  仓库分类: {row['仓库分类']}\n" 
                f"  仓库地址: {row['仓库地址']}\n"
            )
        return warehouse_str

    def _validate_location(self, location: str) -> bool:
        """验证存放位置是否有效"""
        if self.warehouses.empty:
            return True  # 如果没有仓库信息，暂时允许任何位置
        
        return any(location.startswith(warehouse) 
                  for warehouse in self.warehouses['仓库名'].tolist())

    def create_session(self, session_id: str) -> None:
        """创建新的会话"""
        if session_id not in self.conversations:
            self.conversations[session_id] = []
            
    def get_conversation(self, session_id: str) -> List[dict]:
        """获取指定会话的上下文历史"""
        # 如果会话不存在，返回空列表
        if session_id not in self.conversations:
            self.create_session(session_id)
        return self.conversations[session_id][-self.max_history:]  # 只返回最近的消息
        
    def print_conversation(self, session_id: str) -> None:
        """打印指定会话的上下文历史"""
        if session_id not in self.conversations:
            print(f"Session {session_id} does not exist.")
            return
        
        print(f"\n=== Conversation History for Session {session_id} ===")
        for msg in self.conversations[session_id]:
            timestamp = msg.get('timestamp', 'No timestamp')
            print(f"[{timestamp}] {msg['role'].upper()}: {msg['content']}\n")
        print("=" * 50)

    async def chat(self, message: str, user_id: str) -> str:
        try:
            # 初始化 prompt 为系统默认提示词
            prompt = self.system_prompt

            # 如果是入库指令，使用特定的提示词
            if "入库" in message:
                prompt = f"""请帮助收集完整的入库信息。必须包含以下字段：
                - entry_date: 入库日期（YYYY-MM-DD格式）
                - tracking_number: 快递单号
                - phone: 手机号
                - platform: 采购平台
                - warehouse: 包含 name（仓库名）, category（仓库分类）, address（仓库地址）的对象
                - products: 商品数组，每个商品包含 name（商品名）, quantity（数量）, price（单价）

只有在收集到所有必要信息后，才按以下格式输出：
<JSON>
{{
    "entry_date": "YYYY-MM-DD",
    "tracking_number": "xxx",
    "phone": "xxx",
    "platform": "xxx",
    "warehouse": {{
        "name": "xxx",
        "category": "xxx",
        "address": "xxx"
    }},
    "products": [
        {{
            "name": "商品1",
            "quantity": 数量,
            "price": 单价
        }},
        {{
            "name": "商品2",
            "quantity": 数量,
            "price": 单价
        }}
    ]
}}
</JSON>

如果信息不完整，请友好地询问缺失的信息，不要输出JSON格式。
收集完整后，用中文总结入库信息。"""

            # 确保会话存在
            self.create_session(user_id)
            conversation = self.get_conversation(user_id)
            
            # 打印当前上下文信息
            print("\n=== Current Context ===")
            print(f"Session ID: {user_id}")
            print(f"System Prompt: {prompt}")
            print(f"History Length: {len(conversation)}")
            print("=" * 50)

            # 构建消息历史
            messages = []
            # 使用传入的 system_prompt，如果没有则使用默认的
            final_system_prompt = prompt
            if final_system_prompt:
                messages.append({"role": "system", "content": final_system_prompt})
            
            # 添加历史消息
            messages.extend(conversation)
            
            # 添加当前用户消息
            messages.append({"role": "user", "content": message})
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.api_base}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.model,
                            "messages": messages
                        },
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        assistant_message = result["choices"][0]["message"]["content"]
                        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # 更新会话历史，添加时间戳
                        self.conversations[user_id].append({
                            "role": "user",
                            "content": message,
                            "timestamp": current_time
                        })
                        self.conversations[user_id].append({
                            "role": "assistant",
                            "content": assistant_message,
                            "timestamp": current_time
                        })
                        
                        # 修改检查逻辑，只在找到完整的 JSON 时才尝试写入
                        if "<JSON>" in assistant_message and "</JSON>" in assistant_message:
                            json_match = re.search(r'<JSON>(.*?)</JSON>', assistant_message, re.DOTALL)
                            if json_match:
                                json_str = json_match.group(1).strip()
                                try:
                                    data = json.loads(json_str)
                                    # 验证数据是否完整
                                    if self._validate_inventory_data(data):
                                        # 数据完整才写入表格
                                        self._write_inventory_record(assistant_message)
                                        # 保存这条成功消息后清除历史
                                        self.clear_session(user_id)
                                        # 重新添加系统提示词，为下一次对话做准备
                                        if final_system_prompt:
                                            self.conversations[user_id].append({
                                                "role": "system", 
                                                "content": final_system_prompt
                                            })
                                except Exception as e:
                                    logger.error(f"处理 JSON 数据时出错: {str(e)}")
                                    # 不中断对话，继续收集信息
                        
                        # 正常的历史记录管理
                        if len(self.conversations[user_id]) > self.max_history * 2:
                            self.conversations[user_id] = self.conversations[user_id][-self.max_history * 2:]
                        
                        return assistant_message
                    else:
                        raise Exception(f"API 调用失败: {response.status_code} - {response.text}")
                    
            except Exception as e:
                raise Exception(f"与 DeepSeek 通信时发生错误: {str(e)}")
            
        except Exception as e:
            raise Exception(f"与 DeepSeek 通信时发生错误: {str(e)}")
            
    def clear_session(self, session_id: str) -> None:
        """清除指定会话的上下文历史"""
        if session_id in self.conversations:
            self.conversations[session_id] = []

    def _process_inventory_message(self, message: str) -> None:
        """处理入库相关的消息"""
        try:
            # 尝试从消息中提取 JSON 数据
            json_match = re.search(r'<JSON>(.*?)</JSON>', message, re.DOTALL)
            if not json_match:
                logger.info("消息中未找到 JSON 数据")
                return None
                
            json_str = json_match.group(1).strip()
            new_data = json.loads(json_str)
            
            # 将新数据合并到现有数据中
            self.current_inventory_data.update(new_data)
            
            # 检查是否所有必要信息都已收集
            required_fields = {
                'entry_date': '入库日期',
                'tracking_number': '快递单号',
                'phone': '手机号',
                'platform': '采购平台',
                'warehouse': {
                    'name': '仓库名',
                    'category': '仓库分类',
                    'address': '仓库地址'
                },
                'products': ['name', 'quantity', 'price']
            }
            
            missing_fields = self._check_missing_fields(required_fields)
            
            if missing_fields:
                # 构建当前已收集数据的 JSON 响应
                response_data = {
                    'status': 'incomplete',
                    'current_data': self.current_inventory_data,
                    'missing_fields': missing_fields
                }
                return response_data
            
            # 所有信息收集完毕，可以写入数据库
            self._write_inventory_record(self.current_inventory_data)
            
            # 写入成功后清空当前数据并返回成功响应
            response_data = {
                'status': 'success',
                'message': '入库信息已成功记录'
            }
            self.current_inventory_data = {}
            return response_data
            
        except json.JSONDecodeError:
            logger.error("JSON 解析错误")
            return {'status': 'error', 'message': 'JSON 格式错误'}
        except Exception as e:
            logger.error(f"处理入库记录时发生错误: {str(e)}", exc_info=True)
            return {'status': 'error', 'message': str(e)}
            
    def _write_inventory_record(self, message: str) -> None:
        """解析入库信息并写入库存明细表"""
        try:
            # 如果输入是字符串，尝试提取 JSON
            if isinstance(message, str):
                json_match = re.search(r'<JSON>(.*?)</JSON>', message, re.DOTALL)
                if not json_match:
                    logger.error("消息中未找到 JSON 数据")
                    raise ValueError("消息中未找到 JSON 数据")
                json_str = json_match.group(1).strip()
                logger.info(f"提取到的 JSON 字符串: {json_str}")
                data = json.loads(json_str)
            else:
                data = message
            
            logger.info(f"待验证的数据: {json.dumps(data, ensure_ascii=False, indent=2)}")

            # 验证数据完整性
            if not self._validate_inventory_data(data):
                raise ValueError("数据不完整或格式错误")

            # 遍历所有商品，为每个商品创建一条记录
            success = True
            for product in data['products']:
                # 转换数据格式以匹配 inventory 表的结构
                inventory_data = {
                    '入库日期': data['entry_date'],
                    '快递单号': data['tracking_number'],
                    '快递手机号': data['phone'],
                    '采购平台': data['platform'],
                    '商品名称': product['name'],
                    '入库数量': product['quantity'],
                    '入库单价': product['price'],
                    '仓库名': data['warehouse']['name'],
                    '仓库分类': data['warehouse']['category'],
                    '仓库地址': data['warehouse']['address']
                }

                # 写入数据库
                try:
                    if not self.inventory_manager.add_inventory(inventory_data):
                        success = False
                        logger.error(f"写入商品 {product['name']} 的记录失败")
                except Exception as e:
                    success = False
                    logger.error(f"写入商品 {product['name']} 的记录时发生错误: {str(e)}")

            if success:
                logger.info("所有入库记录已成功写入")
            else:
                raise Exception("部分或全部记录写入失败")

        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析错误: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"处理入库记录时发生错误: {str(e)}")
            raise

    def _validate_inventory_data(self, data: dict) -> bool:
        """验证库存数据的完整性"""
        try:
            required_fields = {
                'entry_date': str,
                'tracking_number': str,
                'phone': str,
                'platform': str,
                'warehouse': dict,
                'products': list
            }
            
            # 检查所有必需字段是否存在且不为空
            for field, field_type in required_fields.items():
                if field not in data:
                    logger.info(f"缺少必要字段: {field}")
                    return False
                if not isinstance(data[field], field_type):
                    logger.info(f"字段 {field} 类型错误")
                    return False
                # 检查字符串字段是否为空
                if field_type == str and not data[field].strip():
                    logger.info(f"字段 {field} 为空")
                    return False
                
            # 验证 warehouse 字段
            warehouse_fields = {'name', 'category', 'address'}
            for field in warehouse_fields:
                if field not in data['warehouse'] or not data['warehouse'][field].strip():
                    logger.info(f"warehouse 字段 {field} 缺失或为空")
                    return False
            
            # 验证 products 字段
            if not data['products']:
                logger.info("products 列表为空")
                return False
            
            product_fields = {'name', 'quantity', 'price'}
            for product in data['products']:
                for field in product_fields:
                    if field not in product or not str(product[field]).strip():
                        logger.info(f"product 字段 {field} 缺失或为空")
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"数据验证过程中发生错误: {str(e)}")
            return False


# 使用示例
async def main():
    deepseek = DeepSeekChat()  # 移除了不存在的 Config 参数
    
    # 创建新会话
    session_id = "user_123"
    
    # 发送消息
    response = await deepseek.chat("你好！", session_id)
    print(response)
    
    # 打印当前会话历史
    deepseek.print_conversation(session_id)
    
    # 继续对话（会保持上下文）
    response = await deepseek.chat("请继续我们的对话", session_id)
    print(response)
    
    # 清除会话历史
    deepseek.clear_session(session_id)
    
    # 开始新对话
    response = await deepseek.chat("这是一个新的对话", session_id)
    print(response)

if __name__ == "__main__":
    asyncio.run(main())