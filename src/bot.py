import lark_oapi as lark
from config import FEISHU_CONFIG

## P2ImMessageReceiveV1 为接收消息 v2.0；CustomizedEvent 内的 message 为接收消息 v1.0。
def do_p2_im_message_receive_v1(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    print(f'[ do_p2_im_message_receive_v1 access ], data: {lark.JSON.marshal(data, indent=4)}')

def do_message_event(data: lark.CustomizedEvent) -> None:
    print(f'[ do_customized_event access ], type: message, data: {lark.JSON.marshal(data, indent=4)}')

event_handler = lark.EventDispatcherHandler.builder("", "") \
    .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
    .register_p1_customized_event('im.message.receive_v1', do_message_event) \
    .build()

def main():
    cli = lark.ws.Client(FEISHU_CONFIG["APP_ID"], FEISHU_CONFIG["APP_SECRET"],
                         event_handler=event_handler,
                         log_level=lark.LogLevel.DEBUG)
    cli.start()

if __name__ == "__main__":
    main()