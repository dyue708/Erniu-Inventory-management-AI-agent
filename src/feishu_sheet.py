from typing import List, Dict
import requests
from datetime import datetime, timedelta
import time
import logging

class FeishuSheet:
    def __init__(self, app_id: str, app_secret: str, tables_config: Dict = None):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = "https://open.feishu.cn/open-apis"
        self.token = None
        self.token_expire_time = None
        self.tables = tables_config or {}
        self.max_retries = 3
        self.timeout = 10  # 请求超时时间（秒）
        # logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def _make_request(self, method: str, url: str, headers: Dict, json: Dict = None, retry_count: int = 0) -> Dict:
        """统一的请求处理方法，包含重试逻辑"""
        try:
            # Log request details
            # self.logger.info(f"Request Details:")
            # self.logger.info(f"Method: {method}")
            # self.logger.info(f"URL: {url}")
            # self.logger.info(f"Headers: {headers}")
            # self.logger.info(f"Body: {json}")
            # self.logger.info(f"Timeout: {self.timeout}")
            # self.logger.info(f"Retry Count: {retry_count}")

            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                timeout=self.timeout
            )
            data = response.json()
            
            # Log response
            self.logger.info(f"Response: {data}")
            
            if data.get("code") == 0:
                return data
            
            # 如果是token过期，刷新token后重试
            if data.get("code") == 99991663 and retry_count < self.max_retries:
                self.token = None
                self.logger.info("Token expired, refreshing...")
                return self._make_request(method, url, headers, json, retry_count + 1)
                
            raise Exception(f"API请求失败: {data}")
            
        except requests.exceptions.Timeout:
            if retry_count < self.max_retries:
                self.logger.warning(f"请求超时，第{retry_count + 1}次重试")
                time.sleep(1)  # 重试前等待1秒
                return self._make_request(method, url, headers, json, retry_count + 1)
            raise Exception("请求超时，已达到最大重试次数")
            
        except Exception as e:
            self.logger.error(f"请求异常: {str(e)}")
            raise

    def _get_access_token(self) -> str:
        """获取访问令牌"""
        if self.token and self.token_expire_time and datetime.now() < self.token_expire_time:
            return self.token

        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        
        data = self._make_request("POST", url, headers, payload)
        self.token = data.get("tenant_access_token")
        self.token_expire_time = datetime.now() + timedelta(minutes=115)
        return self.token

    def read_sheet(self, table_name: str = None, spreadsheet_token: str = None, 
                  sheet_id: str = None, range: str = None) -> List[List]:
        """读取表格数据"""
        if table_name:
            if table_name not in self.tables:
                raise ValueError(f"表格 {table_name} 未配置")
            config = self.tables[table_name]
            spreadsheet_token = config.get("spreadsheet_token")
            sheet_id = config.get("sheet_id")
            range = config.get("range", "A:D")  # 默认范围

        if not all([spreadsheet_token, sheet_id, range]):
            raise ValueError("需要提供完整的表格信息")

        url = f"{self.base_url}/sheets/v2/spreadsheets/{spreadsheet_token}/values/{sheet_id}!{range}"
        headers = {"Authorization": f"Bearer {self._get_access_token()}"}
        
        data = self._make_request("GET", url, headers)
        return data.get("data", {}).get("valueRange", {}).get("values", [])

    def write_sheet(self, table_name: str = None, values: List[List] = None,
                   spreadsheet_token: str = None, sheet_id: str = None, 
                   range: str = None) -> None:
        """写入表格数据"""
        if table_name:
            if table_name not in self.tables:
                raise ValueError(f"表格 {table_name} 未配置")
            config = self.tables[table_name]
            spreadsheet_token = config.get("spreadsheet_token")
            sheet_id = config.get("sheet_id")
            range = config.get("range", "A:D")  # 默认范围

        if not all([spreadsheet_token, sheet_id, range, values]):
            raise ValueError("需要提供完整的表格信息和数据")

        # 更新为 v3 API
        url = f"{self.base_url}/sheets/v2/spreadsheets/{spreadsheet_token}/values_append"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }

        payload =  {"valueRange":{
            "range": f"{sheet_id}!{range}",
            "values": values
        }}
    
        self._make_request("POST", url, headers, payload)
