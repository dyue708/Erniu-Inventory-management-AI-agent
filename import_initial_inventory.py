import pandas as pd
from datetime import datetime
import sys
import os


# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 添加src目录到Python路径
src_dir = os.path.join(current_dir, 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# 设置工作目录
os.chdir(current_dir)


from src.table_manage import InboundManager, InventorySummaryManager

def import_initial_inventory(csv_file_path):
    """
    从CSV文件导入期初入库数据
    
    Args:
        csv_file_path: CSV文件路径
    """
    try:
        # 读取CSV文件
        print(f"正在读取文件: {csv_file_path}")
        df = pd.read_csv(csv_file_path)
        
        # 检查必要的列是否存在
        required_columns = ['入库单号', '入库日期', '商品ID', '商品名称', 
                           '仓库名', '入库数量', '入库单价', '入库总价', '供应商', '仓库地址']
        
        for col in required_columns:
            if col not in df.columns:
                print(f"错误: CSV文件缺少必要的列 '{col}'")
                return False
        
        # 初始化入库管理器
        inbound_mgr = InboundManager()
        
        # 准备入库数据
        inbound_data_list = []
        
        # 使用固定的操作者ID
        operator_id = "ou_97a9b0e1496c1b504db73f460d7466bc"
        
        # 遍历CSV中的每一行
        for _, row in df.iterrows():
            # 将日期字符串转换为时间戳（如果是字符串格式）
            inbound_date = row['入库日期']
            if isinstance(inbound_date, str):
                try:
                    # 尝试解析日期字符串
                    date_obj = datetime.strptime(inbound_date, '%Y/%m/%d')
                    inbound_date = int(date_obj.timestamp() * 1000)  # 转换为毫秒级时间戳
                except ValueError:
                    print(f"警告: 无法解析日期 '{inbound_date}'，使用当前时间")
                    inbound_date = int(datetime.now().timestamp() * 1000)
            
            # 确保快递单号和手机号是字符串
            express_no = row.get('快递单号', '')
            express_no = str(express_no) if not pd.isna(express_no) else ''
            
            express_phone = row.get('快递手机号', '')
            express_phone = str(express_phone) if not pd.isna(express_phone) else ''
            
            # 构建入库记录，确保数值字段是有效的JSON数值
            inbound_record = {
                "fields": {
                    "入库单号": row['入库单号'],
                    "入库日期": inbound_date,
                    "商品ID": row['商品ID'],
                    "商品名称": row['商品名称'],
                    "入库数量": float(row['入库数量']),
                    "入库单价": float(row['入库单价']),
                    "入库总价": float(row['入库总价']),
                    "供应商": row['供应商'],
                    "仓库名": row['仓库名'],
                    "仓库地址": row['仓库地址'],
                    "快递单号": express_no,
                    "快递手机号": express_phone,
                    "仓库备注": "",
                    "操作时间": int(datetime.now().timestamp() * 1000),  # 使用当前时间
                    "操作者ID": [{"id": operator_id}]  # 使用正确的格式：列表中包含带有id键的字典
                }
            }
            
            # 确保所有浮点数都在有效范围内
            for key, value in inbound_record["fields"].items():
                if isinstance(value, float):
                    # 检查是否为无穷大或NaN
                    if not (float('-inf') < value < float('inf')) or pd.isna(value):
                        print(f"警告: 字段 '{key}' 的值 {value} 超出有效范围，设置为0")
                        inbound_record["fields"][key] = 0.0
            
            inbound_data_list.append(inbound_record)
        
        # 打印导入的数据
        print(f"准备导入 {len(inbound_data_list)} 条记录:")
        for i, record in enumerate(inbound_data_list):
            fields = record['fields']
            print(f"记录 {i+1}: 商品={fields['商品名称']}, 数量={fields['入库数量']}, 单价={fields['入库单价']}")
        
        # 确认导入
        confirm = input("确认导入这些数据? (y/n): ")
        if confirm.lower() != 'y':
            print("导入已取消")
            return False
        
        # 执行入库操作
        print("开始导入数据...")
        result = inbound_mgr.add_inbound(inbound_data_list)
        
        if result:
            print("数据导入成功!")
            
            # 查看导入后的库存状态
            inventory_mgr = InventorySummaryManager()
            for record in inbound_data_list:
                fields = record['fields']
                product_id = fields['商品ID']
                stock = inventory_mgr.get_stock_summary(product_id=product_id)
                print(f"商品 {product_id} ({fields['商品名称']}) 当前库存:")
                print(stock)
            
            return True
        else:
            print("数据导入失败!")
            return False
            
    except Exception as e:
        print(f"导入过程中发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 检查命令行参数
    if len(sys.argv) > 1:
        csv_file_path = sys.argv[1]
    else:
        # 默认文件路径
        csv_file_path = "期初入库0228.csv"
    
    # 检查文件是否存在
    if not os.path.exists(csv_file_path):
        print(f"错误: 文件 '{csv_file_path}' 不存在")
        sys.exit(1)
    
    # 导入数据
    success = import_initial_inventory(csv_file_path)
    
    # 设置退出代码
    sys.exit(0 if success else 1) 