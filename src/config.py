"""
兼容性配置模块 - 保持向后兼容
"""
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# 导入新的配置管理器
try:
    from config_validator import ApplicationConfig
    _NEW_CONFIG_AVAILABLE = True
except ImportError:
    _NEW_CONFIG_AVAILABLE = False
    logging.warning("New configuration system not available, using legacy config")

# 尝试加载 .env 文件（可选）
def _try_load_env():
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent.parent

    env_path = base_path / '.env'
    if env_path.exists():
        load_dotenv(env_path)

# 加载环境变量（可选）
_try_load_env()

# 全局配置实例
_app_config = None

def get_app_config():
    """获取应用配置实例"""
    global _app_config
    if _app_config is None and _NEW_CONFIG_AVAILABLE:
        try:
            _app_config = ApplicationConfig()
            return _app_config
        except Exception as e:
            logging.warning(f"Failed to load new config, using legacy: {e}")
    return None

# 尝试使用新配置系统
app_config = get_app_config()

if app_config and _NEW_CONFIG_AVAILABLE:
    # 使用新配置系统
    try:
        FEISHU_CONFIG = app_config.get_feishu_config()
        DEEPSEEK_CONFIG = app_config.get_deepseek_config()
    except Exception as e:
        logging.error(f"Failed to get config from new system: {e}")
        app_config = None

# 如果新配置系统不可用，使用旧配置
if not app_config or not _NEW_CONFIG_AVAILABLE:
    # 飞书配置 - 直接设置默认值
    FEISHU_CONFIG = {
        # App 凭证
        "APP_ID": os.getenv("FEISHU_APP_ID"),  # 替换为实际的 APP_ID
        "APP_SECRET": os.getenv("FEISHU_APP_SECRET"),  # 替换为实际的 APP_SECRET

        # 机器人配置
        "VERIFICATION_TOKEN": os.getenv("FEISHU_VERIFICATION_TOKEN"),  # 替换为实际的 Token
        "ENCRYPT_KEY": os.getenv("FEISHU_ENCRYPT_KEY"),  # 替换为实际的 Key

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
