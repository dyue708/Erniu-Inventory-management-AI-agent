import pandas as pd
from config import FEISHU_CONFIG
from feishu_sheet import FeishuSheet

class BaseTableManager:
    def __init__(self):
        self.sheet_client = FeishuSheet(
            app_id=FEISHU_CONFIG["APP_ID"],
            app_secret=FEISHU_CONFIG["APP_SECRET"],
            tables_config=FEISHU_CONFIG["TABLES"]
        )

class WarehouseManager(BaseTableManager):
    TABLE_NAME = "warehouse"
    COLUMNS = ['编号', '仓库名', '仓库分类', '仓库地址']

    def get_data(self) -> pd.DataFrame:
        """查看仓库数据"""
        try:
            data = self.sheet_client.read_sheet(table_name=self.TABLE_NAME)
            if not data or len(data) <= 1:
                return pd.DataFrame()
            
            df = pd.DataFrame(data[1:], columns=self.COLUMNS)
            return df
        except Exception as e:
            print(f"读取库存数据失败: {e}")
            return pd.DataFrame()

    def update_data(self, warehouse_name: str, category: str, address: str) -> None:
        """更新仓库数据"""
        # 构造新数据
        df = self.get_data()
        next_id = str(len(df) + 1) if not df.empty else "1"
        new_data = [[next_id, warehouse_name, category, address]]
        
        # 直接追加到表格末尾
        self.sheet_client.write_sheet(
            table_name=self.TABLE_NAME,
            values=new_data
        )
        

class InventoryManager(BaseTableManager):
    TABLE_NAME = "inventory"
    COLUMNS = ['入库日期', '快递单号', '快递手机号', '采购平台', '入库数量', '入库单价', '存放位置']

    def add_inventory(self, data: dict) -> None:
        """添加库存记录"""
        try:
            # 构造新数据行
            new_data = [[
                data.get('入库日期', ''),
                data.get('快递单号', ''),
                data.get('快递手机号', ''),
                data.get('采购平台', ''),
                data.get('入库数量', ''),
                data.get('入库单价', ''),
                data.get('存放位置', '')
            ]]
            
            # 写入表格
            self.sheet_client.write_sheet(
                table_name=self.TABLE_NAME,
                values=new_data
            )
        except Exception as e:
            print(f"添加库存记录失败: {e}")
            raise

def handle_warehouse_operations():
    warehouse_manager = WarehouseManager()
    
    while True:
        print("\n仓库管理系统")
        print("1. 查看仓库")
        print("2. 更新仓库")
        print("3. 返回主菜单")
        
        choice = input("请选择操作 (1-3): ")

        if choice == "1":
            df = warehouse_manager.get_data()
            if df.empty:
                print("仓库为空")
            else:
                print("\n仓库信息:")
                print(df.to_string(index=False))

        elif choice == "2":
            warehouse_name = input("请输入仓库名称: ")
            category = input("请输入仓库分类: ")
            address = input("请输入仓库地址: ")
            
            try:
                warehouse_manager.update_data(warehouse_name, category, address)
                print("更新成功！")
            except Exception as e:
                print(f"更新失败: {e}")

        elif choice == "3":
            break

        else:
            print("无效的选择，请重试")

def main():
    while True:
        print("\n主菜单")
        print("1. 仓库管理")
        print("2. 退出")
        
        choice = input("请选择操作 (1-2): ")

        if choice == "1":
            handle_warehouse_operations()
        elif choice == "2":
            print("感谢使用！")
            break
        else:
            print("无效的选择，请重试")

if __name__ == "__main__":
    main()

