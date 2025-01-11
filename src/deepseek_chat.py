import logging
from typing import List, Optional
import json
from config import DEEPSEEK_CONFIG, FEISHU_CONFIG
import asyncio
from feishu_sheet import FeishuSheet
import re
from datetime import datetime
from table_manage import (
    WarehouseManager, 
    ProductManager, 
    InboundManager, 
    OutboundManager, 
    InventorySummaryManager
)
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
        self.system_prompt = """你是一个出入库管理助手。你需要帮助收集完整的出入库信息，并以JSON格式返回。
在处理出库请求时，你需要先检查库存是否充足。

你需要从用户的描述中判断是入库还是出库操作：
- 入库相关词语：进货、入库、到货、进仓、收货、采购到货等
- 出库相关词语：出货、出库、发货、提货、销售出库、提货等

如果无法从用户描述中确定操作类型，请询问：
"请问您是要进行入库还是出库操作？"

必要的信息字段包括：
[
    {
        "操作类型": "入库或出库",
        "出入库日期": "操作日期（YYYY-MM-DD格式，默认今天）",
        "商品ID": "商品ID（文本格式）",
        "商品名称": "商品名称",
        "入库数量": 数字类型的数量（入库时使用）,
        "出库数量": 数字类型的数量（出库时使用）,
        "入库单价": 数字类型的单价（入库时使用）,
        "出库单价": 数字类型的单价（出库时使用）,
        "仓库名": "仓库名称",
        "仓库备注": "仓库备注",
        "仓库地址": "仓库地址",
        "供应商": "入库时的供应商名称（仅入库时需要）",
        "客户": "出库时的客户名称（仅出库时需要）",
        "快递单号": "快递单号",
        "快递手机号": "手机号"
    }
]

注意事项：
1. 优先从用户描述中判断操作类型
2. 如果无法判断操作类型，必须先询问清楚
3. 数量和单价必须是纯数字，不能包含单位
4. 日期必须是 YYYY-MM-DD 格式
5. 每条记录的所有字段都不能为空
6. 操作类型必须是"入库"或"出库"
7. 根据操作类型使用对应的字段：
   - 入库时使用：入库数量、入库单价、供应商（客户字段留空）
   - 出库时使用：出库数量、出库单价、客户（供应商字段留空）
8. 商品名称必须与商品列表中的名称完全匹配。如果用户提供的是商品别称：
   - 先检查商品列表的备注字段中是否包含该别称
   - 如果找到匹配的别称，使用对应的标准商品名称
   - 如果别称未在备注中找到：
     - 告知用户该商品不在系统中
     - 展示可用的商品列表及其别称
     - 请用户使用标准商品名称或已登记的别称
9. 如果提交信息不足以确定商品名称（例如用户只提供了商品分类，但该分类下有多个商品），需要：
   - 告知用户需要更具体的商品信息
   - 展示该分类下的所有商品列表
   - 请用户明确选择具体的商品名称
10. 如果仓库名称不正确，需要：
     - 告知用户仓库名称不存在
     - 展示所有可用的仓库列表
     - 请用户从可用仓库列表中选择
10. 当用户一次性提供多个商品的出入库信息时，需要将每个商品的信息作为单独的记录返回在数组中
11. 对于出库操作，在处理前需要检查库存：
   - 使用 inventory_summary 表检查每个商品的库存
   - 如果任何商品库存不足，立即告知用户具体哪些商品库存不足
   - 只有当所有商品库存充足时才继续处理出库请求

请按以下格式返回数据：
1. 如果信息完整且商品名称匹配（对于出库还需要库存充足）：
<JSON>
[
    {第一条完整的记录},
    {第二条完整的记录},
    ...
]
</JSON>
{操作类型}信息已收集完整，我已记录。
{操作类型}商品明细:
1. {商品名称1}: {数量1}
2. {商品名称2}: {数量2}
...

2. 如果商品名称不匹配：
抱歉，以下商品不在系统中：
- {商品名称1}
- {商品名称2}
...
以下是可用的商品列表：
{可用商品列表}
请确认商品名称是否输入错误，或从以上列表中选择正确的商品名称。

3. 如果库存不足（出库时）：
抱歉，以下商品库存不足：
- {商品名称1}: 需要 {需求数量1}, 当前库存 {库存数量1}
- {商品名称2}: 需要 {需求数量2}, 当前库存 {库存数量2}
...
请调整出库数量或等待库存补充。

4. 如果其他信息不完整：
<JSON>
[
    {当前已收集的记录1},
    {当前已收集的记录2},
    ...
]
</JSON>
请继续提供：[缺失的字段列表]"""

        self.conversations = {}
        self.max_history = DEEPSEEK_CONFIG.get("MAX_HISTORY", 10)
        self.inventory_manager = InventorySummaryManager()
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
            warehouse_str += f"- 仓库名: {row['仓库名']}\n"
            warehouse_str += f"  仓库地址: {row['仓库地址']}\n"
            if pd.notna(row.get('仓库备注')) and row['仓库备注']:
                warehouse_str += f"  仓库备注: {row['仓库备注']}\n"
        return warehouse_str

    def _format_product_info(self) -> str:
        """格式化商品信息为字符串"""
        if self.products.empty:
            return "暂无可用商品信息"
        
        product_str = "可用商品列表：\n"
        for _, row in self.products.iterrows():
            product_str += (
                f"- 商品ID: {row['商品ID']}\n"
                f"  商品名称: {row['商品名称']}\n"
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
            today = datetime.now().strftime("%Y-%m-%d")
            
            # 检查消息中是否包含JSON数据
            json_data = None
            if "<JSON>" in message and "</JSON>" in message:
                # 打印原始消息以便调试
                print(f"原始消息: {message}")
                
                json_matches = re.findall(r'<JSON>(.*?)</JSON>', message, re.DOTALL)
                if json_matches:
                    all_data = []
                    for json_str in json_matches:
                        try:
                            data = json.loads(json_str.strip())
                            # 如果是单个对象，转换为列表
                            if isinstance(data, dict):
                                data = [data]
                            # 如果是列表，扩展到总列表中
                            if isinstance(data, list):
                                all_data.extend(data)
                        except json.JSONDecodeError as e:
                            print(f"JSON 解析错误: {str(e)}, 数据: {json_str}")
                            continue
                    
                    if all_data:
                        json_data = all_data
                        print(f"解析后的完整数据列表: {json_data}")
                        
                        # 验证商品和仓库信息
                        invalid_products = []
                        missing_warehouse = False
                        for data in json_data:
                            # 检查商品是否存在
                            if '商品名称' in data:
                                product_name = data['商品名称']
                                if not any(self.products['商品名称'].str.contains(product_name, case=False)):
                                    invalid_products.append(product_name)
                            
                            # 检查仓库是否存在
                            if '仓库名' in data and data['仓库名']:
                                if not any(self.warehouses['仓库名'].str.contains(data['仓库名'], case=False)):
                                    missing_warehouse = True
                        
                        # 如果有无效的商品或缺少仓库信息，构建提示信息
                        if invalid_products or missing_warehouse:
                            response = ""
                            
                            # 处理无效商品
                            if invalid_products:
                                response += "以下商品不在系统中：\n"
                                for prod in invalid_products:
                                    response += f"- {prod}\n"
                                response += "\n可用的商品列表：\n"
                                response += self._format_product_info()
                                response += "\n请使用正确的商品名称。\n\n"
                            
                            # 处理缺少仓库信息
                            if missing_warehouse:
                                response += "仓库信息有误。可用的仓库列表：\n"
                                response += self._format_warehouse_info()
                                response += "\n请选择正确的仓库。\n"
                            
                            # 保留已收集的信息
                            response += "\n当前已收集的信息：\n<JSON>\n"
                            response += json.dumps(json_data, ensure_ascii=False, indent=2)
                            response += "\n</JSON>\n"
                            
                            return response

            # 确保会话存在
            self.create_session(user_id)
            conversation = self.get_conversation(user_id)
            
            # 生成最终的系统提示词
            warehouse_info = self._format_warehouse_info()
            product_info = self._format_product_info()
            final_system_prompt = f"{self.system_prompt}\n\n今天是 {today}\n\n可用的仓库信息：\n{warehouse_info}\n\n相关商品信息：\n{product_info}"
            
            # 打印当前上下文信息
            print("\n=== Current Context ===")
            print(f"Session ID: {user_id}")
            print(f"System Prompt: {final_system_prompt}")
            print(f"History Length: {len(conversation)}")
            print(f"Current Message: {message}")
            print("=" * 50)

            # 构建消息历史
            messages = []
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
                        
                        # 更新会话历史
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
                                        # 尝试写入表格
                                        try:
                                            self._write_inventory_record(assistant_message)
                                            # 写入成功后的处理
                                            self.clear_session(user_id)
                                            if final_system_prompt:
                                                self.conversations[user_id].append({
                                                    "role": "system", 
                                                    "content": final_system_prompt
                                                })
                                        except Exception as e:
                                            # 写入失败时，修改 AI 的回复
                                            error_msg = f"\n\n写入失败: {str(e)}\n请重试或联系管理员。"
                                            assistant_message += error_msg
                                except Exception as e:
                                    logger.error(f"处理 JSON 数据时出错: {str(e)}")
                                    assistant_message += f"\n\n数据处理失败: {str(e)}\n请检查数据格式是否正确。"

                        # 正常的历史记录管理
                        if len(self.conversations[user_id]) > self.max_history * 2:
                            self.conversations[user_id] = self.conversations[user_id][-self.max_history * 2:]
                        
                        return assistant_message
                    else:
                        raise Exception(f"API 调用失败: {response.status_code} - {response.text}")
                    
            except Exception as e:
                raise Exception(f"与 DeepSeek 通信时发生错误: {str(e)}")
            
        except Exception as e:
            error_msg = f"处理请求时发生错误: {str(e)}"
            logger.error(error_msg)
            return error_msg
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
        """解析出入库信息并写入相应的表格"""
        try:
            if isinstance(message, str):
                json_match = re.search(r'<JSON>(.*?)</JSON>', message, re.DOTALL)
                if not json_match:
                    logger.error("消息中未找到 JSON 数据")
                    raise ValueError("消息中未找到 JSON 数据")
                json_str = json_match.group(1).strip()
                data = json.loads(json_str)
                
                # 确保数据是列表格式
                if isinstance(data, dict):
                    data = [data]
                
                # 如果是出库操作，先检查所有商品的库存
                if data[0]['操作类型'] == '出库':
                    insufficient_stock = []
                    for record in data:
                        is_sufficient, current_stock = self._check_stock(
                            record['商品ID'],
                            record['仓库名'],
                            float(record['出库数量'])
                        )
                        if not is_sufficient:
                            insufficient_stock.append({
                                'name': record['商品名称'],
                                'required': float(record['出库数量']),
                                'current': current_stock
                            })
                    
                    if insufficient_stock:
                        error_msg = "以下商品库存不足：\n"
                        for item in insufficient_stock:
                            error_msg += f"- {item['name']}: 需要 {item['required']}, 当前库存 {item['current']}\n"
                        error_msg += "\n请调整出库数量或等待库存补充。"
                        raise ValueError(error_msg)

                # 为每条记录添加时间和用户标记
                current_time = int(datetime.now().timestamp() * 1000)  # 毫秒级时间戳
                processed_records = []
                
                for record in data:
                    record['操作时间'] = current_time
                    record['操作者ID'] = [{"id": self.current_user_id}] if self.current_user_id else []
                    
                    # 验证数据完整性
                    if not self._validate_inventory_data(record):
                        logger.error(f"数据验证失败: {record}")
                        continue

                    # 转换日期为时间戳
                    try:
                        date_obj = datetime.strptime(record['出入库日期'], '%Y-%m-%d')
                        record['出入库日期'] = int(date_obj.timestamp() * 1000)
                    except ValueError as e:
                        logger.error(f"日期格式转换错误: {str(e)}")
                        continue

                    processed_records.append(record)

                if not processed_records:
                    raise ValueError("没有有效的记录可以处理")

                print(f"处理后的记录列表: {processed_records}")
                
                # 根据操作类型选择相应的管理器
                if processed_records[0]['操作类型'] == '入库':
                    manager = InboundManager()
                    if not manager.add_inbound(processed_records):
                        raise Exception("写入入库记录失败")
                else:  # 出库
                    manager = OutboundManager()
                    if not manager.add_outbound(processed_records):
                        raise Exception("写入出库记录失败")

                logger.info(f"成功写入 {len(processed_records)} 条记录")

        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析错误: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"处理出入库记录时发生错误: {str(e)}")
            raise

    def _validate_inventory_data(self, data: dict) -> bool:
        """验证库存数据的完整性"""
        try:
            # 如果收到的是列表，验证每个元素
            if isinstance(data, list):
                return all(self._validate_inventory_data(item) for item in data)
            
            # 基础必要字段列表
            base_fields = {
                '出入库日期': str,
                '商品ID': str,
                '商品名称': str,
                '仓库名': str,
                '仓库备注': str,
                '仓库地址': str,
                '操作类型': str,
                '快递单号': str,
                '快递手机号': str
            }
            
            # 根据操作类型添加相应的必要字段
            if data.get('操作类型') == '入库':
                base_fields.update({
                    '入库数量': (int, float),
                    '入库单价': (int, float),
                    '供应商': str
                })
            elif data.get('操作类型') == '出库':
                base_fields.update({
                    '出库数量': (int, float),
                    '出库单价': (int, float),
                    '客户': str
                })
            else:
                logger.info("操作类型必须是'入库'或'出库'")
                return False
            
            # 检查所有必需字段是否存在且不为空
            for field, field_type in base_fields.items():
                if field not in data:
                    logger.info(f"缺少必要字段: {field}")
                    return False
                    
                # 对于商品ID，确保它是字符串类型
                if field == '商品ID':
                    data[field] = str(data[field])
                
                if not isinstance(data[field], field_type):
                    if isinstance(field_type, tuple):
                        if not any(isinstance(data[field], t) for t in field_type):
                            logger.info(f"字段 {field} 类型错误")
                            return False
                    else:
                        logger.info(f"字段 {field} 类型错误")
                        return False
                        
                # 检查字符串字段是否为空
                if isinstance(data[field], str) and not data[field].strip():
                    logger.info(f"必要字段 {field} 为空")
                    return False
                    
            # 验证数字字段是否为正数
            if data['操作类型'] == '入库':
                if float(data['入库数量']) <= 0:
                    logger.info("入库数量必须大于0")
                    return False
                if float(data['入库单价']) <= 0:
                    logger.info("入库单价必须大于0")
                    return False
            else:  # 出库
                if float(data['出库数量']) <= 0:
                    logger.info("出库数量必须大于0")
                    return False
                if float(data['出库单价']) <= 0:
                    logger.info("出库单价必须大于0")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"数据验证过程中发生错误: {str(e)}")
            return False

    def _check_stock(self, product_id: str, warehouse: str, required_qty: float) -> tuple[bool, float]:
        """检查商品库存是否充足
        
        Args:
            product_id: 商品ID
            warehouse: 仓库名
            required_qty: 需要的数量
            
        Returns:
            tuple[bool, float]: (是否充足, 当前库存)
        """
        try:
            stock_df = self.inventory_manager.get_stock_summary(
                product_id=product_id,
                warehouse=warehouse
            )
            
            if stock_df.empty:
                return False, 0
            
            current_stock = float(stock_df['当前库存'].sum())
            return current_stock >= required_qty, current_stock
            
        except Exception as e:
            logger.error(f"检查库存时发生错误: {str(e)}")
            return False, 0


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