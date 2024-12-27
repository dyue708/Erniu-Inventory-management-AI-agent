import pandas as pd
from config import FEISHU_CONFIG
from feishu_sheet import FeishuSheet

class WarehouseManager:
    def __init__(self):
        self.sheet_client = FeishuSheet(
            app_id=FEISHU_CONFIG["APP_ID"],
            app_secret=FEISHU_CONFIG["APP_SECRET"],
            tables_config=FEISHU_CONFIG["TABLES"]
        )

    def get_warehouse(self) -> pd.DataFrame:
        """查看仓库数据"""
        try:
            data = self.sheet_client.read_sheet(table_name="warehouse")
            if not data or len(data) <= 1:
                return pd.DataFrame()
            
            # 表格结构：编号、仓库名、仓库分类、仓库地址
            columns = ['编号', '仓库名', '仓库分类', '仓库地址']
            df = pd.DataFrame(data[1:], columns=columns)
            return df
        except Exception as e:
            print(f"读取库存数据失败: {e}")
            return pd.DataFrame()

    def update_warehouse(self, product_name: str, quantity: int, note: str = "") -> None:
        """更新仓库数据"""
        # 获取当前数据
        df = self.get_warehouse()
        
        # 更新或添加新记录
        current_time = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
        new_data = pd.DataFrame({
            '编号': [product_name],
            '仓库名': [quantity],
            '仓库分类': [current_time],
            '仓库地址': [note]
        })

        if product_name in df['编号'].values:
            df.loc[df['编号'] == product_name] = new_data.iloc[0]
        else:
            df = pd.concat([df, new_data], ignore_index=True)

        # 写回表格
        values = [df.columns.tolist()] + df.values.tolist()
        self.sheet_client.write_sheet(
            table_name="warehouse",
            values=values
        )


def main():
    # 创建仓库管理器实例
    warehouse = WarehouseManager()

    while True:
        print("\n仓库管理系统")
        print("1. 查看仓库")
        print("2. 更新仓库")
        print("3. 退出")
        
        choice = input("请选择操作 (1-3): ")

        if choice == "1":
            df = warehouse.get_warehouse()
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
                warehouse.update_warehouse(warehouse_name, category, address)
                print("更新成功！")
            except Exception as e:
                print(f"更新失败: {e}")

        elif choice == "3":
            print("感谢使用！")
            break

        else:
            print("无效的选择，请重试")

if __name__ == "__main__":
    main()

