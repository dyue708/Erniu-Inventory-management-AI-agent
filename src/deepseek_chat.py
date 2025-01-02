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
        base_prompt = """你是一个出入库管理助手。你需要收集以下信息来完成入库记录:
- 入库日期(如未指定则使用当前时间)
- 快递单号
- 快递手机号
- 采购平台
- 商品信息(可包含多个商品):
  * 商品名称
  * 入库数量
  * 入库单价
- 存放位置(请从以下仓库中选择):
  * 仓库名
  * 仓库分类
  * 仓库地址

当收集到所有必要信息后，请按以下格式回复：
1. 首先输出 <JSON> 开始标记
2. 然后输出包含所有收集信息的 JSON 数据
3. 输出 </JSON> 结束标记
4. 最后用简短友好的语言总结录入信息

JSON 数据结构示例：
{
    "entry_date": "2024-03-20",
    "tracking_number": "SF1234567",
    "phone": "13800138000",
    "platform": "淘宝",
    "warehouse": {
        "name": "仓库A",
        "category": "电子产品",
        "address": "北京市"
    },
    "products": [
        {
            "name": "商品1",
            "quantity": 10,
            "price": 99.9
        }
    ]
}"""
        
        # 在系统提示词中添加今日日期和可用仓库信息
        today = datetime.now().strftime("%Y-%m-%d")
        warehouse_info = self._format_warehouse_info()
        self.system_prompt = f"{base_prompt}\n今天是 {today}\n\n可用的仓库信息：\n{warehouse_info}"
        
        self.conversations = {}
        self.max_history = DEEPSEEK_CONFIG.get("MAX_HISTORY", 10)
        self.inventory_manager = InventoryManager()

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
                prompt = f"""请将以下入库信息解析为JSON格式。必须包含以下字段：
                - entry_date: 入库日期（YYYY-MM-DD格式）
                - tracking_number: 快递单号
                - phone: 手机号
                - platform: 采购平台
                - warehouse: 包含 name（仓库名）, category（仓库分类）, address（仓库地址）的对象
                - products: 商品数组，每个商品包含 name（商品名）, quantity（数量）, price（单价）

用户消息：{message}

请确保返回的JSON格式如下：
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

然后用中文总结一下入库信息。"""

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
                        
                        # 检查是否完成入库操作
                        if "已成功录入" in assistant_message:
                            try:
                                # 解析入库信息并写入表格
                                self._write_inventory_record(assistant_message)
                                
                                # 保存这条成功消息后清除历史
                                self.clear_session(user_id)
                                # 重新添加系统提示词，为下一次对话做准备
                                if final_system_prompt:
                                    self.conversations[user_id].append({"role": "system", "content": final_system_prompt})
                            except Exception as e:
                                return f"数据处理过程中出现错误：{str(e)}"
                        
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

    def _write_inventory_record(self, message: str) -> None:
        """解析入库信息并写入库存明细表"""
        try:
            # 提取 JSON 数据
            json_match = re.search(r'<JSON>(.*?)</JSON>', message, re.DOTALL)
            if not json_match:
                logger.error("未找到有效的 JSON 数据，原始消息：%s", message)
                raise Exception("未找到有效的 JSON 数据")
            
            json_str = json_match.group(1).strip()
            logger.info("提取的 JSON 数据: %s", json_str)
            
            data = json.loads(json_str)
            logger.info("解析后的数据: %s", data)
            
            # 验证必要字段
            required_fields = ['entry_date', 'tracking_number', 'phone', 'platform', 'warehouse', 'products']
            missing_fields = [field for field in required_fields if field not in data]
            if missing_fields:
                raise Exception(f"JSON 数据缺少必要字段: {', '.join(missing_fields)}")
            
            # 使用 InventoryManager 写入记录
            success_count = 0
            total_products = len(data['products'])
            
            for product in data['products']:
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
                logger.info("准备写入数据: %s", inventory_data)
                
                if self.inventory_manager.add_inventory(inventory_data):
                    success_count += 1
                    logger.info("成功写入商品记录: %s", product['name'])
                else:
                    logger.error("写入商品记录失败: %s", product['name'])
            
            if success_count < total_products:
                raise Exception(f"部分商品写入失败: 成功 {success_count}/{total_products}")
            
            logger.info("所有商品记录写入成功: %d/%d", success_count, total_products)
                
        except json.JSONDecodeError as e:
            logger.error("JSON 解析失败: %s", str(e), exc_info=True)
            raise Exception(f"JSON 解析失败: {str(e)}")
        except Exception as e:
            logger.error("解析或写入入库信息失败: %s", str(e), exc_info=True)
            raise Exception(str(e))


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