"""
配置验证和管理模块
"""
import os
from typing import Dict, Any, Optional, List
from pathlib import Path
from dotenv import load_dotenv
import sys
import logging
from dataclasses import dataclass
from exceptions import ConfigurationError, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class ConfigField:
    """配置字段定义"""
    name: str
    required: bool = True
    default: Any = None
    validator: Optional[callable] = None
    description: str = ""


class ConfigValidator:
    """配置验证器"""

    def __init__(self, config_fields: List[ConfigField]):
        self.config_fields = {field.name: field for field in config_fields}
        self.validated_config = {}

    def validate_field(self, field: ConfigField, value: Any) -> Any:
        """验证单个字段"""
        if value is None:
            if field.required:
                raise ValidationError(
                    f"Required configuration field '{field.name}' is missing",
                    field=field.name
                )
            return field.default

        if field.validator:
            try:
                return field.validator(value)
            except Exception as e:
                raise ValidationError(
                    f"Validation failed for field '{field.name}': {str(e)}",
                    field=field.name,
                    cause=e
                )

        return value

    def validate_all(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """验证所有配置字段"""
        validated = {}

        for field_name, field in self.config_fields.items():
            value = config_dict.get(field_name)
            validated[field_name] = self.validate_field(field, value)

        self.validated_config = validated
        return validated

    def get_config_summary(self) -> Dict[str, Any]:
        """获取配置摘要（隐藏敏感信息）"""
        summary = {}
        sensitive_keys = ['secret', 'key', 'token', 'password']

        for key, value in self.validated_config.items():
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                summary[key] = "***" if value else None
            else:
                summary[key] = value

        return summary


def load_env_file(env_file: Optional[str] = None) -> bool:
    """加载环境变量文件"""
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent.parent

    if env_file:
        env_path = Path(env_file)
    else:
        env_path = base_path / '.env'

    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Loaded environment variables from {env_path}")
        return True
    else:
        logger.warning(f"Environment file not found: {env_path}")
        return False


def validate_url(url: str) -> str:
    """验证URL格式"""
    if not url:
        raise ValidationError("URL cannot be empty")
    if not (url.startswith('http://') or url.startswith('https://')):
        raise ValidationError("URL must start with http:// or https://")
    return url


def validate_non_empty_string(value: str) -> str:
    """验证非空字符串"""
    if not value or not value.strip():
        raise ValidationError("Value cannot be empty")
    return value.strip()


def validate_positive_int(value: Any) -> int:
    """验证正整数"""
    try:
        int_val = int(value)
        if int_val <= 0:
            raise ValidationError("Value must be positive")
        return int_val
    except (ValueError, TypeError):
        raise ValidationError("Value must be a valid integer")


# 定义配置字段
FEISHU_CONFIG_FIELDS = [
    ConfigField(
        "FEISHU_APP_ID",
        required=True,
        validator=validate_non_empty_string,
        description="飞书应用ID"
    ),
    ConfigField(
        "FEISHU_APP_SECRET",
        required=True,
        validator=validate_non_empty_string,
        description="飞书应用密钥"
    ),
    ConfigField(
        "FEISHU_VERIFICATION_TOKEN",
        required=True,
        validator=validate_non_empty_string,
        description="飞书验证Token"
    ),
    ConfigField(
        "FEISHU_ENCRYPT_KEY",
        required=True,
        validator=validate_non_empty_string,
        description="飞书加密Key"
    ),
    ConfigField(
        "FEISHU_BITABLE_APP_TOKEN",
        required=True,
        validator=validate_non_empty_string,
        description="飞书多维表格应用Token"
    ),
]

BITABLE_CONFIG_FIELDS = [
    ConfigField(
        "WAREHOUSE_BITABLE_ID",
        required=True,
        validator=validate_non_empty_string,
        description="仓库管理表ID"
    ),
    ConfigField(
        "PRODUCT_BITABLE_ID",
        required=True,
        validator=validate_non_empty_string,
        description="商品管理表ID"
    ),
    ConfigField(
        "INVENTORY_BITABLE_ID",
        required=False,
        description="库存明细表ID"
    ),
    ConfigField(
        "INVENTORY_SUMMARY_BITABLE_ID",
        required=True,
        validator=validate_non_empty_string,
        description="库存汇总表ID"
    ),
    ConfigField(
        "INBOUND_BITABLE_ID",
        required=True,
        validator=validate_non_empty_string,
        description="入库明细表ID"
    ),
    ConfigField(
        "OUTBOUND_BITABLE_ID",
        required=True,
        validator=validate_non_empty_string,
        description="出库明细表ID"
    ),
]

DEEPSEEK_CONFIG_FIELDS = [
    ConfigField(
        "DEEPSEEK_API_KEY",
        required=True,
        validator=validate_non_empty_string,
        description="DeepSeek API密钥"
    ),
    ConfigField(
        "DEEPSEEK_BASE_URL",
        required=True,
        validator=validate_url,
        description="DeepSeek API基础URL"
    ),
    ConfigField(
        "DEEPSEEK_MODEL",
        required=True,
        validator=validate_non_empty_string,
        description="DeepSeek模型名称"
    ),
    ConfigField(
        "DEEPSEEK_MAX_HISTORY",
        required=False,
        default=10,
        validator=validate_positive_int,
        description="最大历史记录数"
    ),
]

APP_CONFIG_FIELDS = [
    ConfigField(
        "MESSAGE_DIR",
        required=False,
        default="messages",
        description="消息存储目录"
    ),
    ConfigField(
        "LOG_LEVEL",
        required=False,
        default="INFO",
        description="日志级别"
    ),
    ConfigField(
        "HEALTH_CHECK_PORT",
        required=False,
        default=8080,
        validator=validate_positive_int,
        description="健康检查端口"
    ),
]


class ApplicationConfig:
    """应用配置管理器"""

    def __init__(self, env_file: Optional[str] = None):
        self.env_file = env_file
        self._config = {}
        self._load_and_validate()

    def _load_and_validate(self):
        """加载并验证配置"""
        # 加载环境变量
        load_env_file(self.env_file)

        # 获取所有环境变量
        env_vars = dict(os.environ)

        # 验证各个配置组
        validators = {
            'feishu': ConfigValidator(FEISHU_CONFIG_FIELDS),
            'bitable': ConfigValidator(BITABLE_CONFIG_FIELDS),
            'deepseek': ConfigValidator(DEEPSEEK_CONFIG_FIELDS),
            'app': ConfigValidator(APP_CONFIG_FIELDS),
        }

        for config_group, validator in validators.items():
            try:
                validated_config = validator.validate_all(env_vars)
                self._config[config_group] = validated_config
                logger.info(f"Configuration group '{config_group}' validated successfully")
            except (ValidationError, ConfigurationError) as e:
                logger.error(f"Configuration validation failed for group '{config_group}': {e}")
                raise ConfigurationError(
                    f"Invalid configuration for {config_group}: {e.message}",
                    config_key=config_group,
                    cause=e
                )

        logger.info("All configuration validated successfully")

    def get_feishu_config(self) -> Dict[str, Any]:
        """获取飞书配置"""
        feishu_config = self._config['feishu'].copy()
        bitable_config = self._config['bitable'].copy()

        # 构建旧格式的配置以保持兼容性
        return {
            "APP_ID": feishu_config["FEISHU_APP_ID"],
            "APP_SECRET": feishu_config["FEISHU_APP_SECRET"],
            "VERIFICATION_TOKEN": feishu_config["FEISHU_VERIFICATION_TOKEN"],
            "ENCRYPT_KEY": feishu_config["FEISHU_ENCRYPT_KEY"],
            "BITABLES": {
                "warehouse": {
                    "app_token": feishu_config["FEISHU_BITABLE_APP_TOKEN"],
                    "table_id": bitable_config["WAREHOUSE_BITABLE_ID"]
                },
                "product": {
                    "app_token": feishu_config["FEISHU_BITABLE_APP_TOKEN"],
                    "table_id": bitable_config["PRODUCT_BITABLE_ID"]
                },
                "inventory": {
                    "app_token": feishu_config["FEISHU_BITABLE_APP_TOKEN"],
                    "table_id": bitable_config.get("INVENTORY_BITABLE_ID")
                },
                "inventory_summary": {
                    "app_token": feishu_config["FEISHU_BITABLE_APP_TOKEN"],
                    "table_id": bitable_config["INVENTORY_SUMMARY_BITABLE_ID"]
                },
                "inbound": {
                    "app_token": feishu_config["FEISHU_BITABLE_APP_TOKEN"],
                    "table_id": bitable_config["INBOUND_BITABLE_ID"]
                },
                "outbound": {
                    "app_token": feishu_config["FEISHU_BITABLE_APP_TOKEN"],
                    "table_id": bitable_config["OUTBOUND_BITABLE_ID"]
                }
            }
        }

    def get_deepseek_config(self) -> Dict[str, Any]:
        """获取DeepSeek配置"""
        deepseek_config = self._config['deepseek'].copy()
        return {
            "API_KEY": deepseek_config["DEEPSEEK_API_KEY"],
            "BASE_URL": deepseek_config["DEEPSEEK_BASE_URL"],
            "MODEL": deepseek_config["DEEPSEEK_MODEL"],
            "MAX_HISTORY": deepseek_config["DEEPSEEK_MAX_HISTORY"]
        }

    def get_app_config(self) -> Dict[str, Any]:
        """获取应用配置"""
        return self._config['app'].copy()

    def get_config_summary(self) -> Dict[str, Any]:
        """获取配置摘要"""
        summary = {}
        for group_name, group_config in self._config.items():
            validator = ConfigValidator([])
            validator.validated_config = group_config
            summary[group_name] = validator.get_config_summary()
        return summary

    def validate_required_configs(self) -> bool:
        """验证必需的配置是否都已设置"""
        try:
            feishu_config = self.get_feishu_config()
            deepseek_config = self.get_deepseek_config()

            # 检查关键配置
            required_keys = [
                (feishu_config, "APP_ID"),
                (feishu_config, "APP_SECRET"),
                (deepseek_config, "API_KEY"),
            ]

            for config_dict, key in required_keys:
                if not config_dict.get(key):
                    raise ConfigurationError(f"Required configuration missing: {key}")

            return True
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            return False