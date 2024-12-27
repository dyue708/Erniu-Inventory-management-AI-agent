from typing import List, Dict
import requests
from datetime import datetime, timedelta

class FeishuSheet:
    def __init__(self, app_id: str, app_secret: str, tables_config: Dict = None):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = "https://open.feishu.cn/open-apis"
        self.token = None
        self.token_expire_time = None
        self.tables = tables_config or {}

    def _get_access_token(self) -> str:
        """获取访问令牌"""
        if self.token and self.token_expire_time and datetime.now() < self.token_expire_time:
            return self.token

        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        headers = {
            "Content-Type": "application/json; charset=utf-8"
        }
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()
        
        if data.get("code") != 0:
            raise Exception(f"获取token失败: {data}")
        
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
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}"
        }
        
        response = requests.get(url, headers=headers)
        data = response.json()
        
        if data.get("code") != 0:
            raise Exception(f"读取表格失败: {data}")
            
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
            range = config.get("range", "A1")  # 默认起始位置

        if not all([spreadsheet_token, sheet_id, range, values]):
            raise ValueError("需要提供完整的表格信息和数据")

        url = f"{self.base_url}/sheets/v2/spreadsheets/{spreadsheet_token}/values"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}"
        }
        
        payload = {
            "valueRange": {
                "range": f"{sheet_id}!{range}",
                "values": values
            }
        }
        
        response = requests.put(url, headers=headers, json=payload)
        data = response.json()
        
        if data.get("code") != 0:
            raise Exception(f"写入表格失败: {data}")
