# 导入飞书开放平台SDK
import lark_oapi as lark
# 导入飞书配置信息
from config import FEISHU_CONFIG

class FeishuBot:
    """飞书机器人类,用于处理飞书消息事件"""
    
    def __init__(self):
        """初始化飞书机器人,创建事件处理器和客户端"""
        self.event_handler = self._create_event_handler()
        self.client = self._create_client()
    
    def _do_p2_im_message_receive_v1(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        """处理P2P消息接收事件
        Args:
            data: 消息数据
        """
        print(f'[ do_p2_im_message_receive_v1 access ], data: {lark.JSON.marshal(data, indent=4)}')

    def _do_message_event(self, data: lark.CustomizedEvent) -> None:
        """处理自定义消息事件
        Args:
            data: 事件数据
        """
        print(f'[ do_customized_event access ], type: message, data: {lark.JSON.marshal(data, indent=4)}')

    def _create_event_handler(self):
        """创建事件分发处理器
        Returns:
            EventDispatcherHandler: 事件处理器实例
        """
        return lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._do_p2_im_message_receive_v1) \
            .register_p1_customized_event('im.message.receive_v1', self._do_message_event) \
            .build()
    
    def _create_client(self):
        """创建飞书客户端
        Returns:
            Client: 飞书客户端实例
        """
        return lark.ws.Client(
            FEISHU_CONFIG["APP_ID"],
            FEISHU_CONFIG["APP_SECRET"],
            event_handler=self.event_handler,
            log_level=lark.LogLevel.DEBUG
        )
    
    def start(self):
        """启动飞书机器人"""
        self.client.start()

def main():
    """主函数,创建并启动飞书机器人"""
    bot = FeishuBot()
    bot.start()

if __name__ == "__main__":
    main()