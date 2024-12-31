# 导入飞书开放平台SDK
import lark_oapi as lark
# 导入飞书配置信息
from config import FEISHU_CONFIG

class FeishuBot:
    """飞书机器人类，专门用于存储接收到的消息"""
    
    def __init__(self, app_id=None, app_secret=None, verification_token=None, encrypt_key=None, config=None):
        """初始化消息存储机器人，创建事件处理器和客户端
        Args:
            app_id: 应用 ID
            app_secret: 应用密钥
            verification_token: 验证 token
            encrypt_key: 加密密钥
            config: 配置字典，如果单独参数未提供则从此处读取
        """
        # 优先使用单独传入的参数，其次使用config字典，最后使用默认配置
        self.config = self._resolve_config(
            app_id, app_secret, verification_token, encrypt_key, config
        )
        self.event_handler = self._create_event_handler()
        self.client = self._create_client()
    
    def _resolve_config(self, app_id, app_secret, verification_token, encrypt_key, config):
        """解析配置优先级并返回最终配置
        """
        final_config = FEISHU_CONFIG.copy()  # 使用默认配置的副本
        
        if config:
            final_config.update(config)
            
        # 优先使用单独传入的参数
        if app_id:
            final_config["APP_ID"] = app_id
        if app_secret:
            final_config["APP_SECRET"] = app_secret
        if verification_token:
            final_config["VERIFICATION_TOKEN"] = verification_token
        if encrypt_key:
            final_config["ENCRYPT_KEY"] = encrypt_key
            
        return final_config

    def _save_message_to_file(self, message_data: dict, message_type: str):
        """将消息保存到本地文件
        Args:
            message_data: 消息数据
            message_type: 消息类型
        """
        import json
        from datetime import datetime
        import os

        # 确保messages目录存在
        os.makedirs('messages', exist_ok=True)
        
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename = f'messages/message_{timestamp}.json'
        
        # 准备写入的数据
        data = {
            'type': message_type,
            'timestamp': datetime.now().isoformat(),
            'data': message_data
        }
        
        # 写入文件
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _do_p2_im_message_receive_v1(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        """处理P2P消息接收事件"""
        print(f'收到P2P消息接收事件: {lark.JSON.marshal(data, indent=4)}')
        self._save_message_to_file(lark.JSON.marshal(data), 'p2p_message')

    def _do_message_event(self, data: lark.CustomizedEvent) -> None:
        """处理自定义消息事件"""
        print(f'收到自定义消息事件: {lark.JSON.marshal(data, indent=4)}')
        self._save_message_to_file(lark.JSON.marshal(data), 'custom_message')

    def _create_event_handler(self):
        """创建事件分发处理器
        Returns:
            EventDispatcherHandler: 事件处理器实例
        """
        handler = lark.EventDispatcherHandler.builder(
            self.config["VERIFICATION_TOKEN"],
            self.config["ENCRYPT_KEY"]
        )
        
        # 注册 P2P 消息接收事件
        handler.register_p2_im_message_receive_v1(self._do_p2_im_message_receive_v1)
        
        # 注册自定义消息事件
        handler.register_p1_customized_event('im.message.receive_v1', self._do_message_event)
        
        # 注册机器人群组事件处理器
        handler.register_p1_customized_event('im.chat.member.bot.added_v1', self._handle_bot_added)
        handler.register_p1_customized_event('im.chat.member.bot.deleted_v1', self._handle_bot_removed)
        
        # 注册消息回应事件处理器
        handler.register_p1_customized_event('im.message.reaction.created_v1', self._handle_message_reaction)
        
        return handler.build()
    
    def _create_client(self):
        """创建飞书客户端
        Returns:
            Client: 飞书客户端实例
        """
        return lark.ws.Client(
            self.config["APP_ID"],
            self.config["APP_SECRET"],
            event_handler=self.event_handler,
            log_level=lark.LogLevel.DEBUG
        )
    
    def start(self):
        """启动飞书机器人"""
        self.client.start()

    def _handle_bot_added(self, data: lark.CustomizedEvent) -> None:
        """处理机器人被添加到群组的事件"""
        print(f'机器人被添加到群组: {lark.JSON.marshal(data, indent=4)}')

    def _handle_bot_removed(self, data: lark.CustomizedEvent) -> None:
        """处理机器人被移出群组的事件"""
        print(f'机器人被移出群组: {lark.JSON.marshal(data, indent=4)}')

    def _handle_message_reaction(self, data: lark.CustomizedEvent) -> None:
        """处理消息回应事件"""
        print(f'收到消息回应: {lark.JSON.marshal(data, indent=4)}')

def main():
    """主函数，创建并启动消息存储机器人"""
    bot = FeishuBot(config=FEISHU_CONFIG)
    bot.start()

if __name__ == "__main__":
    main()