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

    def _make_request(self, method: str, url: str, headers: Dict, json: Dict = None, params: Dict = None, retry_count: int = 0) -> Dict:
        """统一的请求处理方法，包含重试逻辑"""
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                params=params,
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
                return self._make_request(method, url, headers, json, params, retry_count + 1)
                
            raise Exception(f"API请求失败: {data}")
            
        except requests.exceptions.Timeout:
            if retry_count < self.max_retries:
                self.logger.warning(f"请求超时，第{retry_count + 1}次重试")
                time.sleep(1)  # 重试前等待1秒
                return self._make_request(method, url, headers, json, params, retry_count + 1)
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

    def read_bitable(self, app_token: str, table_id: str, page_size: int = 100, page_token: str = None) -> Dict:
        """读取多维表格数据
        
        Args:
            app_token: 多维表格的应用 token
            table_id: 表格 ID
            page_size: 每页记录数，默认100
            page_token: 分页标记，默认None
            
        Returns:
            Dict: 包含表格数据和元信息的字典
        """
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        params = {
            "page_size": page_size
        }
        if page_token:
            params["page_token"] = page_token
            
        data = self._make_request("GET", url, headers, params)
        return data.get("data", {})

    def write_bitable(self, app_token: str, table_id: str, records: List[Dict]) -> Dict:
        """写入多维表格数据
        
        Args:
            app_token: 多维表格的应用 token
            table_id: 表格 ID
            records: 要写入的记录列表，每条记录为一个字典，格式如：
                    [{"fields": {"字段名1": "值1", "字段名2": "值2"}}]
            
        Returns:
            Dict: API 响应结果
        """
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        payload = {
            "records": records
        }
        
        return self._make_request("POST", url, headers, payload)

    def update_bitable(self, app_token: str, table_id: str, record_id: str, fields: Dict) -> Dict:
        """更新多维表格中的记录
        
        Args:
            app_token: 多维表格的应用 token
            table_id: 表格 ID
            record_id: 记录 ID
            fields: 要更新的字段，格式如：{"字段名1": "新值1"}
            
        Returns:
            Dict: API 响应结果
        """
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        payload = {
            "fields": fields
        }
        
        return self._make_request("PUT", url, headers, payload)

    def update_bitable_fields(self, app_token: str, table_id: str, field_id: str, field_config: Dict) -> Dict:
        """更新多维表格的字段（表头）配置
        
        Args:
            app_token: 多维表格的应用 token
            table_id: 表格 ID
            field_id: 字段 ID
            field_config: 字段配置，格式如：
                       {
                           "field_name": "新字段名",
                           "type": 1,  # 字段类型的数值表示
                           "property": {  # 可选
                               "multiple": True
                           }
                       }
            
        Returns:
            Dict: API 响应结果
        """
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        # 直接使用传入的字段配置
        payload = field_config
        
        self.logger.info(f"Updating field with payload: {payload}")
        
        return self._make_request("PUT", url, headers, json=payload)

    def get_bitable_fields(self, app_token: str, table_id: str) -> List[Dict]:
        """获取多维表格的字段（表头）配置
        
        Args:
            app_token: 多维表格的应用 token
            table_id: 表格 ID
            
        Returns:
            List[Dict]: 字段配置列表，每个字段包含 field_name, type 等信息
        """
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        data = self._make_request("GET", url, headers)
        return data.get("data", {}).get("items", [])

    def create_bitable_field(self, app_token: str, table_id: str, field_config: Dict) -> Dict:
        """创建多维表格的新字段
        
        Args:
            app_token: 多维表格的应用 token
            table_id: 表格 ID
            field_config: 字段配置，格式如：
                       {
                           "field_name": "新字段名",
                           "type": 1,  # 字段类型的数值表示
                           "property": {  # 可选
                               "multiple": True
                           }
                       }
            
        Returns:
            Dict: API 响应结果
        """
        url = f"{self.base_url}/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        return self._make_request("POST", url, headers, json=field_config)

def test_bitable():
    """测试多维表格的读写功能"""
    # 测试配置
    from config import FEISHU_CONFIG
    app_id = FEISHU_CONFIG["APP_ID"]
    app_secret = FEISHU_CONFIG["APP_SECRET"]
    app_token = "KuQabUcsVaQ6rosP5WvcX9denId"
    table_id = "tblg1jHBG0icQM8w"
    
    # 初始化客户端
    feishu = FeishuSheet(app_id=app_id, app_secret=app_secret)
    
    try:
        # 测试读取
        print("开始测试读取...")
        read_result = feishu.read_bitable(
            app_token=app_token,
            table_id=table_id
        )
        print("读取结果:", read_result)
        
        # 测试写入
        print("\n开始测试写入...")
        test_records = [
            {
                "fields": {
                    "文本": "这是一条测试数据"
                }
            }
        ]
        write_result = feishu.write_bitable(
            app_token=app_token,
            table_id=table_id,
            records=test_records
        )
        print("写入结果:", write_result)
        
        # 测试更新
        print("\n开始测试更新...")
        # 读取数据获取第一行的 record_id
        read_result = feishu.read_bitable(
            app_token=app_token,
            table_id=table_id
        )
        
        # 获取第一行记录的 ID
        if read_result and read_result.get("items"):
            first_record_id = read_result["items"][0]["record_id"]
            
            # 更新第一行数据
            update_fields = {
                "文本": "更新第一行的新内容"
            }
            update_result = feishu.update_bitable(
                app_token=app_token,
                table_id=table_id,
                record_id=first_record_id,
                fields=update_fields
            )
            print("更新第一行结果:", update_result)
        else:
            print("没有找到记录")
        
        # 测试获取表头
        print("\n开始测试获取表头...")
        try:
            current_fields = feishu.get_bitable_fields(
                app_token=app_token,
                table_id=table_id
            )
            print("当前表头配置:", current_fields)
            
            # 确保有字段存在
            if current_fields:
                # 获取第一个字段的配置
                first_field = current_fields[0]
                field_id = first_field.get("field_id")  # 获取字段ID
                
                # 创建新的字段配置
                new_field_config = {
                    "field_name": first_field["field_name"] + "_1",  # 在原字段名后添加"_1"
                    "type": first_field["type"],
                }
                # 如果有 property，则保留
                if first_field.get("property"):
                    new_field_config["property"] = first_field["property"]
                
                # 更新表头
                print("\n开始更新表头...")
                fields_result = feishu.update_bitable_fields(
                    app_token=app_token,
                    table_id=table_id,
                    field_id=field_id,  # 使用获取到的field_id
                    field_config=new_field_config
                )
                print("更新表头结果:", fields_result)
            else:
                print("没有找到任何字段配置")
            
        except Exception as e:
            print(f"操作失败: {str(e)}")
        
    except Exception as e:
        print(f"测试过程中发生错误: {str(e)}")

if __name__ == "__main__":
    test_bitable()
