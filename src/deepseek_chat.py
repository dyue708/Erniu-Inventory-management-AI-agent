from typing import List, Optional
import json
from config import DEEPSEEK_CONFIG
import asyncio

class DeepSeekChat:
    def __init__(self):
        self.api_key = DEEPSEEK_CONFIG["API_KEY"]
        self.api_base = DEEPSEEK_CONFIG["BASE_URL"]
        self.model = DEEPSEEK_CONFIG["MODEL"]
        self.system_prompt = DEEPSEEK_CONFIG.get("SYSTEM_PROMPT", None)  # 添加默认系统提示
        self.conversations = {}  # 存储多个会话的上下文
        self.max_history = DEEPSEEK_CONFIG.get("MAX_HISTORY", 10)  # 添加最大历史记录限制

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
            print(f"{msg['role'].upper()}: {msg['content']}\n")
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
                    
                    # 更新会话历史
                    self.conversations[session_id].append({"role": "user", "content": message})
                    self.conversations[session_id].append({"role": "assistant", "content": assistant_message})
                    # 保持历史记录在限制范围内
                    if len(self.conversations[session_id]) > self.max_history * 2:  # 乘2是因为每轮对话有用户和助手两条消息
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