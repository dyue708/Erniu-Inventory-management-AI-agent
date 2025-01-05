import logging
from typing import List, Optional
import json
from config import DEEPSEEK_CONFIG, FEISHU_CONFIG
import asyncio
from feishu_sheet import FeishuSheet
import re
from datetime import datetime
from table_manage import InventoryManager, WarehouseManager,ProductManager
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
        self.product_manager = ProductManager()
        self.warehouses = self._get_warehouses()
        self.products = self._get_products()
        
        # 修改基础系统提示词
        self.system_prompt = """你是一个出入库管理助手。你需要帮助收集完整的入库信息，并以JSON格式返回。

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
            "quantity": 数字类型的数量（不要包含单位）,
            "price": 数字类型的单价（不要包含单位）
        }
    ]
}

注意事项：
1. quantity 和 price 必须是纯数字，不能包含单位
2. 日期必须是 YYYY-MM-DD 格式
3. 所有字段都不能为空
4. 商品名称必须与商品列表中的名称完全匹配，如果用户提供的商品名称不在列表中：
   - 告知用户该商品不在系统中
   - 展示可用的商品列表
   - 请用户确认是否输入错误或选择正确的商品名称
5. 如果提交信息不足以确定商品名称（例如用户只提供了商品分类，但该分类下有多个商品），需要：
   - 告知用户需要更具体的商品信息
   - 展示该分类下的所有商品列表
   - 请用户明确选择具体的商品名称

请按以下格式返回数据：
1. 如果信息完整且商品名称匹配：
<JSON>
{完整的JSON数据}
</JSON>
入库信息已收集完整，我已记录。
入库商品明细:
{商品名称}: {数量}

2. 如果商品名称不匹配：
抱歉，商品"{用户输入的商品名称}"不在系统中。
以下是可用的商品列表：
{可用商品列表}
请确认商品名称是否输入错误，或从以上列表中选择正确的商品名称。

3. 如果其他信息不完整：
<JSON>
{当前已收集的JSON数据}
</JSON>
请继续提供：[缺失的字段列表]"""

        self.conversations = {}
        self.max_history = DEEPSEEK_CONFIG.get("MAX_HISTORY", 10)
        self.inventory_manager = InventoryManager()
        self.current_inventory_data = {}
        self.current_user_id = None

    def _get_warehouses(self) -> pd.DataFrame:
        """获取仓库信息"""
        try:
            return self.warehouse_manager.get_data()
        except Exception as e:
            logger.error(f"获取仓库信息失败: {str(e)}")
            return pd.DataFrame()

    def _get_products(self) -> pd.DataFrame:
        """获取商品信息"""
        try:
            return self.product_manager.get_data()
        except Exception as e:
            logger.error(f"获取商品信息失败: {str(e)}")
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

    def _format_product_info(self) -> str:
        """格式化商品信息为字符串"""
        if self.products.empty:
            return "暂无可用商品信息"
        
        product_str = "可用商品列表：\n"
        for _, row in self.products.iterrows():
            product_str += (
                f"- 商品名称: {row['商品名称']}\n"
                f"  商品分类: {row['商品分类']}\n"
                f"  商品规格: {row['商品规格']}\n"
                f"  商品单位: {row['商品单位']}\n"
            )
            # 只有当备注不为空时才添加备注信息
            if pd.notna(row.get('商品备注')) and row['商品备注']:
                product_str += f"  商品备注: {row['商品备注']}\n"
            product_str += "\n"  # 在每个商品之间添加空行
        return product_str

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
        """处理用户消息并返回回复"""
        try:
            self.current_user_id = user_id
            # 使用统一的系统提示词，不再需要特别判断"入库"指令
            today = datetime.now().strftime("%Y-%m-%d")
            warehouse_info = self._format_warehouse_info()
            product_info = self._format_product_info()
            final_system_prompt = f"{self.system_prompt}\n\n今天是 {today}\n\n可用的仓库信息：\n{warehouse_info}\n\n相关商品信息：\n{product_info}"

            # 确保会话存在
            self.create_session(user_id)
            conversation = self.get_conversation(user_id)
            # 生成最终的系统提示词
            today = datetime.now().strftime("%Y-%m-%d")
            warehouse_info = self._format_warehouse_info()
            product_info = self._format_product_info()
            final_system_prompt = f"{self.system_prompt}\n\n今天是 {today}\n\n可用的仓库信息：\n{warehouse_info}\n\n相关商品信息：\n{product_info}"
            # 打印当前上下文信息
            print("\n=== Current Context ===")
            print(f"Session ID: {user_id}")
            print(f"System Prompt: {final_system_prompt}")  # 使用最终版的系统提示词
            print(f"History Length: {len(conversation)}")
            print(f"Current Message: {message}")  # 添加当前消息内容
            print("=" * 50)

            # 构建消息历史
            messages = []
            # 使用传入的 system_prompt，如果没有则使用默认的
            if final_system_prompt:
                messages.append({"role": "system", "content": final_system_prompt})
            
            # 添加历史消息
            messages.extend(conversation)
            
            # 添加用户消息
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
        finally:
            self.current_user_id = None  # 清理当前用户ID

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
            # 添加用户ID作为写入记录的一部分
            if isinstance(message, str):
                json_match = re.search(r'<JSON>(.*?)</JSON>', message, re.DOTALL)
                if not json_match:
                    logger.error("消息中未找到 JSON 数据")
                    raise ValueError("消息中未找到 JSON 数据")
                json_str = json_match.group(1).strip()
                data = json.loads(json_str)
                
                # 添加写入时间和操作用户标记
                data['write_timestamp'] = int(datetime.now().timestamp())
                operator_id = self.current_user_id
                data['operator_id'] = operator_id
                
                logger.info(f"待验证的数据: {json.dumps(data, ensure_ascii=False, indent=2)}")

                # 验证数据完整性
                if not self._validate_inventory_data(data):
                    raise ValueError("数据不完整或格式错误")

                # 遍历所有商品，为每个商品创建一条记录
                success = True
                for product in data['products']:
                    # 获取当前时间的 Unix timestamp（毫秒级）
                    current_timestamp = int(datetime.now().timestamp() * 1000)
                    
                    # 将入库日期转换为 Unix timestamp（毫秒级）
                    entry_date = int(datetime.strptime(data['entry_date'], '%Y-%m-%d').timestamp() * 1000)
                    
                    # 转换数据格式以匹配 inventory 表的结构
                    inventory_data = {
                        '入库日期': entry_date,  # 毫秒级时间戳
                        '快递单号': data['tracking_number'],
                        '快递手机号': data['phone'],
                        '采购平台': data['platform'],
                        '商品名称': product['name'],
                        '入库数量': product['quantity'],
                        '入库单价': product['price'],
                        '仓库名': data['warehouse']['name'],
                        '仓库分类': data['warehouse']['category'],
                        '仓库地址': data['warehouse']['address'],
                        '操作者ID': [{"id": operator_id}],
                        '操作时间': current_timestamp,  # 毫秒级时间戳
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