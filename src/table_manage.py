import pandas as pd
from config import FEISHU_CONFIG
from feishu_sheet import FeishuSheet
from datetime import datetime

class BaseTableManager:
    def __init__(self):
        self.sheet_client = FeishuSheet(
            app_id=FEISHU_CONFIG["APP_ID"],
            app_secret=FEISHU_CONFIG["APP_SECRET"],
            tables_config=FEISHU_CONFIG["TABLES"]
        )
        self.bitable_config = FEISHU_CONFIG["BITABLES"]
        # Add column validation
        self._validate_and_update_columns()

    def _validate_and_update_columns(self):
        """验证并更新表格列名和字段类型"""
        if not hasattr(self, 'TABLE_NAME') or not hasattr(self, 'COLUMNS'):
            return

        try:
            config = self.bitable_config[self.TABLE_NAME]
            # 获取当前表头配置
            fields = self.sheet_client.get_bitable_fields(
                app_token=config["app_token"],
                table_id=config["table_id"]
            )
            
            # 获取现有字段名和ID的映射
            existing_fields = {field["field_name"]: field for field in fields}
            existing_columns = set(existing_fields.keys())
            desired_columns = set(self.COLUMNS)

            # 检查是否需要添加新列
            missing_columns = desired_columns - existing_columns
            if missing_columns:
                print(f"需要添加的列: {missing_columns}")
                for column_name in missing_columns:
                    field_config = {
                        "field_name": column_name,
                        "type": 1,  # 默认使用文本类型
                    }
                    
                    self.sheet_client.create_bitable_field(
                        app_token=config["app_token"],
                        table_id=config["table_id"],
                        field_config=field_config
                    )
                    print(f"已添加新列: {column_name}")

            # 重新获取更新后的字段配置
            fields = self.sheet_client.get_bitable_fields(
                app_token=config["app_token"],
                table_id=config["table_id"]
            )

            # 定义字段类型映射
            field_types = {
                # 库存表字段类型
                "数量": 2,  # 数字类型
                "单价": 2,  # 数字类型
                "总价": 20,  # 公式类型
                "变动数量": 20,  # 公式类型
                "出入库日期": 5,  # 日期时间类型
                "操作者ID": 11,  # 用户类型
                "操作时间": 5,  # 日期时间类型
                "操作类型": 3,  # 单选类型
            }

            # 更新现有列的类型
            for field in fields:
                field_id = field["field_id"]
                field_name = field["field_name"]
                desired_type = field_types.get(field_name, 1)  # 默认为文本类型
                
                if field["type"] != desired_type:
                    field_config = {
                        "field_name": field_name,
                        "type": desired_type
                    }
                    self.sheet_client.update_bitable_fields(
                        app_token=config["app_token"],
                        table_id=config["table_id"],
                        field_id=field_id,
                        field_config=field_config
                    )
                    print(f"已将字段 '{field_name}' 更新为对应类型")

            # 更新不匹配的列名
            existing_columns = set(field["field_name"] for field in fields)
            if existing_columns != desired_columns:
                print(f"警告: {self.TABLE_NAME} 表格列名不匹配")
                print(f"期望的列名: {self.COLUMNS}")
                print(f"实际的列名: {list(existing_columns)}")
                
                # 更新不匹配的字段名
                for field in fields:
                    field_name = field["field_name"]
                    field_id = field["field_id"]
                    
                    # 如果当前字段名不在期望的列名中，尝试更新为新的列名
                    if field_name not in desired_columns:
                        # 找到一个未使用的期望列名
                        new_name = next((col for col in desired_columns if col not in existing_columns), None)
                        if new_name:
                            # 更新字段配置
                            field_config = {
                                "field_name": new_name,
                                "type": 1  # 确保更新名称时也设置为文本类型
                            }
                            
                            self.sheet_client.update_bitable_fields(
                                app_token=config["app_token"],
                                table_id=config["table_id"],
                                field_id=field_id,
                                field_config=field_config
                            )
                            print(f"已将字段 '{field_name}' 更新为 '{new_name}' (文本类型)")
                            
                            # 更新已存在的列名集合
                            existing_columns.remove(field_name)
                            existing_columns.add(new_name)
                            
        except Exception as e:
            print(f"验证和更新列名时发生错误: {e}")

class WarehouseManager(BaseTableManager):
    TABLE_NAME = "warehouse"
    COLUMNS = [ '仓库名', '仓库分类', '仓库地址']

    def get_data(self) -> pd.DataFrame:
        """查看仓库数据"""
        try:
            config = self.bitable_config[self.TABLE_NAME]
            data = self.sheet_client.read_bitable(
                app_token=config["app_token"],
                table_id=config["table_id"]
            )
            
            if not data or not data.get("items"):
                return pd.DataFrame()
            
            # 转换多维表格数据为DataFrame格式
            records = []
            for item in data["items"]:
                fields = item["fields"]
                records.append([
                    fields.get("仓库名", ""),
                    fields.get("仓库分类", ""),
                    fields.get("仓库地址", "")
                ])
            
            return pd.DataFrame(records, columns=self.COLUMNS)
        except Exception as e:
            print(f"读取库存数据失败: {e}")
            return pd.DataFrame()

    def update_data(self, warehouse_name: str, category: str, address: str) -> None:
        """更新仓库数据"""
        try:
            # 获取当前数据以生成新的编号
            df = self.get_data()
            next_id = str(len(df) + 1) if not df.empty else "1"
            
            # 构造新记录
            new_record = [{
                "fields": {
                    "仓库名": warehouse_name,
                    "仓库分类": category,
                    "仓库地址": address
                }
            }]
            
            config = self.bitable_config[self.TABLE_NAME]
            self.sheet_client.write_bitable(
                app_token=config["app_token"],
                table_id=config["table_id"],
                records=new_record
            )
        except Exception as e:
            raise Exception(f"更新仓库数据失败: {e}")

class InventoryManager(BaseTableManager):
    TABLE_NAME = "inventory"
    COLUMNS = [
        '出入库日期', '快递单号', '快递手机号', '采购平台', '商品ID', '商品名称', '数量', '单价', 
        '仓库名', '仓库分类', '仓库地址', '操作者ID', '操作时间', '总价', '变动数量', '操作类型'
    ]

    def add_inventory(self, data: dict) -> bool:
        """添加库存记录"""
        try:
            # 确保数字类型字段为数字
            try:
                quantity = float(data.get('数量', 0))
                price = float(data.get('单价', 0))
            except (ValueError, TypeError):
                print(f"数字转换失败: 数量={data.get('数量')}, 单价={data.get('单价')}")
                return False

            # 构造新记录
            new_record = [{
                "fields": {
                    "出入库日期": data.get('出入库日期', ''),
                    "快递单号": data.get('快递单号', ''),
                    "快递手机号": data.get('快递手机号', ''),
                    "采购平台": data.get('采购平台', ''),
                    "商品ID": data.get('商品ID', ''),
                    "商品名称": data.get('商品名称', ''),
                    "数量": quantity,
                    "单价": price,
                    "仓库名": data.get('仓库名', ''),
                    "仓库分类": data.get('仓库分类', ''),
                    "仓库地址": data.get('仓库地址', ''),
                    "操作者ID": data.get('操作者ID', ''),
                    "操作时间": data.get('操作时间', ''),
                    "操作类型": data.get('操作类型', '入库')
                }
            }]
            
            config = self.bitable_config[self.TABLE_NAME]
            response = self.sheet_client.write_bitable(
                app_token=config["app_token"],
                table_id=config["table_id"],
                records=new_record
            )
            return True if response else False
            
        except Exception as e:
            print(f"添加库存记录失败: {e}")
            return False

class ProductManager(BaseTableManager):
    TABLE_NAME = "product"
    COLUMNS = ['商品ID', '商品名称', '商品分类', '商品规格', '商品单位', '商品备注']

    def get_data(self) -> pd.DataFrame:
        """查看商品数据"""
        try:
            config = self.bitable_config[self.TABLE_NAME]
            data = self.sheet_client.read_bitable(
                app_token=config["app_token"],
                table_id=config["table_id"]
            )
            
            if not data or not data.get("items"):
                return pd.DataFrame()
            
            # 转换多维表格数据为DataFrame格式
            records = []
            for item in data["items"]:
                fields = item["fields"]
                records.append([
                    fields.get("商品ID", ""),
                    fields.get("商品名称", ""),
                    fields.get("商品分类", ""),
                    fields.get("商品规格", ""),
                    fields.get("商品单位", ""),
                    fields.get("商品备注", "")
                ])
            
            return pd.DataFrame(records, columns=self.COLUMNS)
        except Exception as e:
            print(f"读取商品数据失败: {e}")
            return pd.DataFrame()

def main():
    """测试函数：读取并显示库存表和仓库表数据"""
    try:
        # 初始化管理器
        warehouse_mgr = WarehouseManager()
        inventory_mgr = InventoryManager()
        product_mgr = ProductManager()  # 添加商品管理器实例

        # 读取商品数据
        print("\n=== 商品表数据 ===")
        product_df = product_mgr.get_data()
        print("列名:", product_df.columns.tolist())
        print(product_df)

        # 读取仓库数据
        print("\n=== 仓库表数据 ===")
        warehouse_df = warehouse_mgr.get_data()
        print("列名:", warehouse_df.columns.tolist())
        print(warehouse_df)

        # 读取库存数据
        print("\n=== 库存表数据 ===")
        inventory_data = inventory_mgr.sheet_client.read_bitable(
            app_token=inventory_mgr.bitable_config[inventory_mgr.TABLE_NAME]["app_token"],
            table_id=inventory_mgr.bitable_config[inventory_mgr.TABLE_NAME]["table_id"]
        )
        
        if inventory_data and inventory_data.get("items"):
            records = []
            for item in inventory_data["items"]:
                records.append([item["fields"].get(col, "") for col in inventory_mgr.COLUMNS])
            inventory_df = pd.DataFrame(records, columns=inventory_mgr.COLUMNS)
            print("列名:", inventory_df.columns.tolist())
            print(inventory_df)
        else:
            print("库存表为空")

    except Exception as e:
        print(f"测试过程中发生错误: {e}")

if __name__ == "__main__":
    main()


