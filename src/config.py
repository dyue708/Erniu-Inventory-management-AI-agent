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
    },
    
    # 多维表格配置
    "BITABLES": {
        "warehouse": {  # 仓库管理表
            "app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN"),
            "table_id": os.getenv("WAREHOUSE_BITABLE_ID")
        },
        "product": {    # 商品管理表
            "app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN"), 
            "table_id": os.getenv("PRODUCT_BITABLE_ID")
        },
        "category": {   # 商品分类管理表
            "app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN"),
            "table_id": os.getenv("CATEGORY_BITABLE_ID")
        },
        "inventory": {  # 库存明细表
            "app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN"),
            "table_id": os.getenv("INVENTORY_BITABLE_ID")
        },
        "inventory_summary": {  # 库存汇总表
            "app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN"),
            "table_id": os.getenv("INVENTORY_SUMMARY_BITABLE_ID")
        },
        "inbound": {  # 入库明细表
            "app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN"),
            "table_id": os.getenv("INBOUND_BITABLE_ID")
        },
        "outbound": {  # 出库明细表
            "app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN"),
            "table_id": os.getenv("OUTBOUND_BITABLE_ID")
        }
    }
}

# Deepseek 配置
DEEPSEEK_CONFIG = {
    "API_KEY": os.getenv("DEEPSEEK_API_KEY"),
    "BASE_URL": os.getenv("DEEPSEEK_BASE_URL"),
    "MODEL": os.getenv("DEEPSEEK_MODEL"),
    "MAX_HISTORY": 10
}
