# 导入飞书开放平台SDK
import lark_oapi as lark
import json
import logging
# 导入飞书配置信息
from config import FEISHU_CONFIG
from lark_oapi.event.dispatcher_handler import P2ApplicationBotMenuV6
# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
        try:
            # 优先使用单独传入的参数，其次使用config字典，最后使用默认配置
            self.config = self._resolve_config(
                app_id, app_secret, verification_token, encrypt_key, config
            )
            self.event_handler = self._create_event_handler()
            self.client = self._create_client()
        except Exception as e:
            logger.error(f"初始化飞书机器人失败: {str(e)}", exc_info=True)
            raise
    
    def _resolve_config(self, app_id, app_secret, verification_token, encrypt_key, config):
        """解析配置优先级并返回最终配置
        """
        try:
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
                
            # 验证必要的配置项
            required_keys = ["APP_ID", "APP_SECRET", "VERIFICATION_TOKEN", "ENCRYPT_KEY"]
            for key in required_keys:
                if not final_config.get(key):
                    raise ValueError(f"缺少必要的配置项: {key}")
                    
            return final_config
        except Exception as e:
            logger.error(f"解析配置失败: {str(e)}", exc_info=True)
            raise

    def _save_message_to_file(self, message_data: dict, message_type: str):
        """将消息保存到本地文件，按用户分类存储
        Args:
            message_data: 消息数据
            message_type: 消息类型
        """
        import json
        from datetime import datetime
        import os

        try:
            # 从消息数据中提取用户ID
            data_dict = json.loads(message_data) if isinstance(message_data, str) else message_data
            if message_type == 'bot_menu_event':
                sender_id = data_dict.get('event', {}).get('operator', {}).get('operator_id', {}).get('open_id', 'unknown')
            else:
                sender_id = data_dict.get('event', {}).get('sender', {}).get('sender_id', {}).get('open_id', 'unknown')
        except json.JSONDecodeError as e:
            logger.error(f"解析消息数据失败: {str(e)}")
            sender_id = 'unknown'
        except Exception as e:
            logger.error(f"提取用户ID失败: {str(e)}")
            sender_id = 'unknown'

        try:
            # 创建用户专属的消息目录
            user_message_dir = os.path.join('messages', sender_id)
            os.makedirs(user_message_dir, exist_ok=True)
            
            # 生成带时间戳的文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            filename = os.path.join(user_message_dir, f'message_{timestamp}.json')
            
            # 准备写入的数据
            data = {
                'type': message_type,
                'timestamp': datetime.now().isoformat(),
                'sender_id': sender_id,
                'data': message_data
            }
            
            # 写入文件
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存消息到文件失败: {str(e)}", exc_info=True)

    def _do_p2_im_message_receive_v1(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        """处理P2P消息接收事件"""
        try:
            self._save_message_to_file(lark.JSON.marshal(data), 'p2p_message')
        except Exception as e:
            logger.error(f"处理P2P消息失败: {str(e)}", exc_info=True)

    def _do_group_message_receive(self, data: lark.CustomizedEvent) -> None:
        """处理群组消息接收事件"""
        try:
            message_data = lark.JSON.marshal(data)
            data_dict = json.loads(message_data)
            mentions = data_dict.get('event', {}).get('message', {}).get('mentions', [])
            self._save_message_to_file(message_data, 'group_message')
        except json.JSONDecodeError as e:
            logger.error(f"解析群组消息数据失败: {str(e)}")
        except Exception as e:
            logger.error(f"处理群组消息失败: {str(e)}", exc_info=True)


    def _handle_bot_menu_event(self, data: P2ApplicationBotMenuV6) -> None:
        """Handle bot menu event"""
        try:
            message_data = lark.JSON.marshal(data)
            self._save_message_to_file(message_data, 'bot_menu_event')
        except Exception as e:
            logger.error(f"Failed to handle bot menu event: {str(e)}", exc_info=True)

    def _create_event_handler(self):
        """Create event dispatcher handler
        Returns:
            EventDispatcherHandler: Event handler instance
        """
        try:
            handler = lark.EventDispatcherHandler.builder(
                self.config["VERIFICATION_TOKEN"],
                self.config["ENCRYPT_KEY"]
            )
            
            # 注册 P2P 消息接收事件
            handler.register_p2_im_message_receive_v1(self._do_p2_im_message_receive_v1)
            
            # 注册群组消息接收事件（合并了自定义消息处理）
            handler.register_p1_customized_event('im.message.receive_v1', self._do_group_message_receive)
            
            # 注册机器人群组事件处理器
            handler.register_p1_customized_event('im.chat.member.bot.added_v1', self._handle_bot_added)
            handler.register_p1_customized_event('im.chat.member.bot.deleted_v1', self._handle_bot_removed)
            
            # 注册消息回应事件处理器
            handler.register_p1_customized_event('im.message.reaction.created_v1', self._handle_message_reaction)
                        
            # 注册菜单操作事件处理器
            handler.register_p2_application_bot_menu_v6(self._handle_bot_menu_event)
            
            return handler.build()
        except Exception as e:
            logger.error(f"Failed to create event handler: {str(e)}", exc_info=True)
            raise
    
    def _create_client(self):
        """创建飞书客户端
        Returns:
            Client: 飞书客户端实例
        """
        try:
            return lark.ws.Client(
                self.config["APP_ID"],
                self.config["APP_SECRET"],
                event_handler=self.event_handler,
                log_level=lark.LogLevel.INFO
            )
        except Exception as e:
            logger.error(f"创建飞书客户端失败: {str(e)}", exc_info=True)
            raise
    
    def start(self):
        """启动飞书机器人"""
        try:
            self.client.start()
        except Exception as e:
            logger.error(f"启动飞书机器人失败: {str(e)}", exc_info=True)
            raise

    def _handle_bot_added(self, data: lark.CustomizedEvent) -> None:
        """处理机器人被添加到群组的事件"""
        try:
            logger.info("机器人被添加到群组")
            # 在这里添加具体的处理逻辑
        except Exception as e:
            logger.error(f"处理机器人添加事件失败: {str(e)}", exc_info=True)

    def _handle_bot_removed(self, data: lark.CustomizedEvent) -> None:
        """处理机器人被移出群组的事件"""
        try:
            logger.info("机器人被移出群组")
            # 在这里添加具体的处理逻辑
        except Exception as e:
            logger.error(f"处理机器人移除事件失败: {str(e)}", exc_info=True)

    def _handle_message_reaction(self, data: lark.CustomizedEvent) -> None:
        """处理消息回应事件"""
        try:
            logger.info("收到消息回应")
            # 在这里添加具体的处理逻辑
        except Exception as e:
            logger.error(f"处理消息回应事件失败: {str(e)}", exc_info=True)

def main():
    """主函数，创建并启动消息存储机器人"""
    try:
        bot = FeishuBot(config=FEISHU_CONFIG)
        bot.start()
    except Exception as e:
        logger.error(f"主程序运行失败: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    main()