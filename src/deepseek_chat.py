from typing import List, Optional
import json
from config import DEEPSEEK_CONFIG, FEISHU_CONFIG
import asyncio
from feishu_sheet import FeishuSheet
import re
from datetime import datetime

class DeepSeekChat:
    def __init__(self):
        self.api_key = DEEPSEEK_CONFIG["API_KEY"]
        self.api_base = DEEPSEEK_CONFIG["BASE_URL"]
        self.model = DEEPSEEK_CONFIG["MODEL"]
        self.system_prompt = DEEPSEEK_CONFIG.get("SYSTEM_PROMPT", None)  # 添加默认系统提示
        self.conversations = {}  # 存储多个会话的上下文，现在每条消息将包含时间戳
        self.max_history = DEEPSEEK_CONFIG.get("MAX_HISTORY", 10)  # 添加最大历史记录限制
        
        # 初始化飞书表格操作对象
        self.sheet = FeishuSheet(
            app_id=FEISHU_CONFIG["APP_ID"],
            app_secret=FEISHU_CONFIG["APP_SECRET"],
            tables_config=FEISHU_CONFIG["TABLES"]
        )

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

    async def chat(self, message: str, session_id: str, system_prompt: Optional[str] = None) -> str:
        """与 DeepSeek 进行对话"""
        import httpx
        
        # 确保会话存在
        self.create_session(session_id)
        conversation = self.get_conversation(session_id)
        
        # 打印当前上下文信息
        print("\n=== Current Context ===")
        print(f"Session ID: {session_id}")
        print(f"System Prompt: {system_prompt or self.system_prompt}")
        print(f"History Length: {len(conversation)}")
        print("=" * 50)

        # 构建消息历史
        messages = []
        # 使用传入的 system_prompt，如果没有则使用默认的
        final_system_prompt = system_prompt or self.system_prompt
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
                    self.conversations[session_id].append({
                        "role": "user",
                        "content": message,
                        "timestamp": current_time
                    })
                    self.conversations[session_id].append({
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
                            self.clear_session(session_id)
                            # 重新添加系统提示词，为下一次对话做准备
                            if final_system_prompt:
                                self.conversations[session_id].append({"role": "system", "content": final_system_prompt})
                        except Exception as e:
                            return f"数据处理过程中出现错误：{str(e)}"
                    
                    # 正常的历史记录管理
                    if len(self.conversations[session_id]) > self.max_history * 2:
                        self.conversations[session_id] = self.conversations[session_id][-self.max_history * 2:]
                    
                    return assistant_message
                else:
                    raise Exception(f"API 调用失败: {response.status_code} - {response.text}")
                    
        except Exception as e:
            raise Exception(f"与 DeepSeek 通信时发生错误: {str(e)}")
            
    def clear_session(self, session_id: str) -> None:
        """清除指定会话的上下文历史"""
        if session_id in self.conversations:
            self.conversations[session_id] = []

    def _write_inventory_record(self, message: str) -> None:
        """解析入库信息并写入库存明细表"""
        try:
            # 解析入库信息
            date_match = re.search(r"入库日期[：:]\s*(\d{4}-\d{2}-\d{2})", message)
            entry_date = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")
            
            tracking_match = re.search(r"快递单号[：:]\s*([^\n]+)", message)
            tracking_number = tracking_match.group(1) if tracking_match else ""
            
            phone_match = re.search(r"快递手机号[：:]\s*(\d+)", message)
            phone = phone_match.group(1) if phone_match else ""
            
            platform_match = re.search(r"采购平台[：:]\s*([^\n]+)", message)
            platform = platform_match.group(1) if platform_match else ""
            
            location_match = re.search(r"存放位置[：:]\s*([^\n]+)", message)
            location = location_match.group(1) if location_match else ""
            
            # 解析商品信息
            products = []
            product_pattern = r"商品名称[：:]\s*([^\n]+).*?数量[：:]\s*(\d+).*?单价[：:]\s*([\d.]+)"
            for match in re.finditer(product_pattern, message, re.DOTALL):
                products.append({
                    'name': match.group(1).strip(),
                    'quantity': int(match.group(2)),
                    'price': float(match.group(3))
                })
            
            logger.info(f"开始写入库存记录，共 {len(products)} 条商品信息")
            
            # 写入库存明细表
            for product in products:
                try:
                    record = [
                        entry_date,                # 入库日期
                        tracking_number,           # 快递单号
                        phone,                     # 快递手机号
                        platform,                  # 采购平台
                        product['name'],          # 商品名称
                        product['quantity'],      # 入库数量
                        product['price'],         # 入库单价
                        location                  # 存放位置
                    ]
                    self.sheet.write_sheet('inventory', [record])
                    logger.info(f"成功写入商品记录: {product['name']}")
                except Exception as e:
                    logger.error(f"写入商品 {product['name']} 记录失败: {str(e)}", exc_info=True)
                    raise
                
        except Exception as e:
            logger.error(f"解析或写入入库信息失败: {str(e)}", exc_info=True)
            raise Exception(f"解析入库信息失败: {str(e)}")


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