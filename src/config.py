import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 飞书配置
FEISHU_CONFIG = {
    # App 凭证
    "APP_ID": os.getenv("FEISHU_APP_ID"),
    "APP_SECRET": os.getenv("FEISHU_APP_SECRET"),
    
    # 机器人配置
    "VERIFICATION_TOKEN": os.getenv("FEISHU_VERIFICATION_TOKEN"),
    "ENCRYPT_KEY": os.getenv("FEISHU_ENCRYPT_KEY"),
    # 表格配置
    "TABLES": {
        "warehouse": {  # 仓库管理表
            "spreadsheet_token": os.getenv("FEISHU_SHEET_TOKEN"),
            "sheet_id": os.getenv("WAREHOUSE_SHEET_ID")
        },
        "product": {    # 商品管理表
            "spreadsheet_token": os.getenv("FEISHU_SHEET_TOKEN"),
            "sheet_id": os.getenv("PRODUCT_SHEET_ID")
        },
        "category": {   # 商品分类管理表
            "spreadsheet_token": os.getenv("FEISHU_SHEET_TOKEN"),
            "sheet_id": os.getenv("CATEGORY_SHEET_ID")
        },
        "inventory": {  # 库存明细表
            "spreadsheet_token": os.getenv("FEISHU_SHEET_TOKEN"),
            "sheet_id": os.getenv("INVENTORY_SHEET_ID")
        }
    }
}

# Deepseek 配置
DEEPSEEK_CONFIG = {
    "API_KEY": os.getenv("DEEPSEEK_API_KEY"),
    "BASE_URL": os.getenv("DEEPSEEK_BASE_URL"),
    "MODEL": os.getenv("DEEPSEEK_MODEL"),
    "SYSTEM_PROMPT": "你是一个出入库管理助手。你需要收集以下信息来完成入库记录:\n- 入库日期\n- 快递单号\n- 快递手机号\n- 采购平台\n- 入库数量\n- 入库单价\n- 存放位置\n\n如果用户提供的信息不完整,你需要友好地提醒用户补充缺失的信息。当收集到所有必要信息后,你应该回复'已成功录入'并总结录入的信息。请始终保持专业和耐心的态度。",
    "MAX_HISTORY": 10
}
