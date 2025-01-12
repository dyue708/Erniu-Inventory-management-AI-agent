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
        if not hasattr(self, 'TABLE_NAME') or not hasattr(self, 'COLUMNS') or not hasattr(self, 'FIELD_TYPES'):
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
                        "type": self.FIELD_TYPES.get(column_name, 1),  # 使用预设的类型
                    }
                    
                    self.sheet_client.create_bitable_field(
                        app_token=config["app_token"],
                        table_id=config["table_id"],
                        field_config=field_config
                    )
                    print(f"已添加新列: {column_name}")

            # 只更新预设列中需要特殊类型的字段
            for field in fields:
                field_name = field["field_name"]
                # 只处理预设列中的字段
                if field_name in desired_columns:
                    desired_type = self.FIELD_TYPES.get(field_name, 1)  # 如果没有特殊设置，默认为文本类型
                    field_config = {
                        "field_name": field_name,
                        "type": desired_type
                    }
                    
                    # 为日期时间类型添加格式化配置
                    if desired_type == 5:  # 日期时间类型
                        field_config["property"] = {
                            "auto_fill": False,
                            "date_formatter": "yyyy-MM-dd HH:mm"
                        }
                        # 出入库日期使用不同的格式
                        if field_name in ['出库日期', '入库日期']:
                            field_config["property"]["date_formatter"] = "yyyy-MM-dd"
                    
                    # 如果字段需要特殊类型且当前类型不匹配，则更新
                    if (field_name in self.FIELD_TYPES and 
                        (field["type"] != desired_type or 
                         (desired_type == 5 and field.get("property", {}).get("date_formatter") != field_config.get("property", {}).get("date_formatter")))):
                        
                        self.sheet_client.update_bitable_fields(
                            app_token=config["app_token"],
                            table_id=config["table_id"],
                            field_id=field["field_id"],
                            field_config=field_config
                        )
                        print(f"已将字段 '{field_name}' 更新为对应类型和格式")

        except Exception as e:
            print(f"验证和更新列名时发生错误: {e}")

class WarehouseManager(BaseTableManager):
    TABLE_NAME = "warehouse"
    COLUMNS = ['仓库名', '仓库备注', '仓库地址']
    FIELD_TYPES = {
        "仓库名": 1,  # 文本类型
        "仓库备注": 1,  # 文本类型
        "仓库地址": 1,  # 文本类型
    }

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
                    fields.get("仓库备注", ""),
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
                    "仓库备注": category,
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

class InboundManager(BaseTableManager):
    TABLE_NAME = "inbound"
    COLUMNS = [
        '入库单号', '入库日期', '快递单号', '快递手机号', '供应商', '商品ID', '商品名称', '入库数量', '入库单价', 
        '仓库名', '仓库备注', '仓库地址', '操作者ID', '操作时间', '入库总价'
    ]
    FIELD_TYPES = {
        "入库单号": 1,  # 文本类型
        "入库日期": 5,  # 日期时间类型
        "快递单号": 1,  # 文本类型
        "快递手机号": 1,  # 文本类型
        "供应商": 1,  # 文本类型
        "商品ID": 1,  # 文本类型
        "商品名称": 1,  # 文本类型
        "入库数量": 2,  # 数字类型
        "入库单价": 2,  # 数字类型
        "仓库名": 1,  # 文本类型
        "仓库备注": 1,  # 文本类型
        "仓库地址": 1,  # 文本类型
        "操作者ID": 11,  # 用户类型
        "操作时间": 5,  # 日期时间类型
        "入库总价": 2,  # 数字类型
    }

    def add_inbound(self, data_list: list[dict]) -> bool:
        """添加多条入库记录
        Args:
            data_list: 包含多个商品入库信息的列表
        """
        try:
            success_count = 0
            inventory_mgr = InventorySummaryManager()
            config = self.bitable_config[self.TABLE_NAME]

            # 为整批次生成一个入库单号
            inbound_no = f"IN-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            print(f"生成入库单号: {inbound_no}")

            for data in data_list:
                try:
                    # 获取字段数据
                    fields = data.get('fields', data)
                    
                    # 打印调试信息
                    print(f"处理入库数据: {fields}")
                    
                    # 确保数值字段正确
                    quantity = float(fields.get('入库数量', 0))
                    price = float(fields.get('入库单价', 0))

                    if quantity <= 0 or price <= 0:
                        print(f"入库数量或单价无效: 入库数量={quantity}, 入库单价={price}")
                        continue

                    # 构造入库记录，使用相同的入库单号
                    new_record = [{
                        "fields": {
                            "入库单号": inbound_no,  # 使用同一个入库单号
                            "入库日期": fields.get('出入库日期', ''),
                            "快递单号": fields.get('快递单号', ''),
                            "快递手机号": fields.get('快递手机号', ''),
                            "供应商": fields.get('供应商', ''),
                            "商品ID": fields.get('商品ID', ''),
                            "商品名称": fields.get('商品名称', ''),
                            "入库数量": quantity,
                            "入库单价": price,
                            "仓库名": fields.get('仓库名', ''),
                            "仓库备注": fields.get('仓库备注', ''),
                            "仓库地址": fields.get('仓库地址', ''),
                            "操作者ID": fields.get('操作者ID', ''),
                            "操作时间": fields.get('操作时间', ''),
                            "入库总价": quantity * price
                        }
                    }]

                    print(f"准备写入入库记录: {new_record}")
                    
                    response = self.sheet_client.write_bitable(
                        app_token=config["app_token"],
                        table_id=config["table_id"],
                        records=new_record
                    )
                    
                    if response:
                        # 构造用于更新库存的数据
                        inventory_data = {
                            "商品ID": fields.get('商品ID', ''),
                            "商品名称": fields.get('商品名称', ''),
                            "仓库名": fields.get('仓库名', ''),
                            "入库数量": quantity,
                            "入库单价": price
                        }
                        print(f"准备更新库存汇总: {inventory_data}")
                        
                        if inventory_mgr.update_inbound(inventory_data):
                            success_count += 1
                            print(f"成功处理第 {success_count} 条记录")
                        else:
                            print("更新库存汇总失败")
                            return False
                    else:
                        print("写入入库记录失败")
                        return False
                
                except (ValueError, TypeError) as e:
                    print(f"处理数据时发生错误: {e}")
                    return False

            return success_count == len(data_list)
            
        except Exception as e:
            print(f"添加入库记录失败: {e}")
            return False

class OutboundManager(BaseTableManager):
    TABLE_NAME = "outbound"
    COLUMNS = [
        '出库单号', '出库日期', '快递单号', '快递手机号', '客户', '商品ID', '商品名称', 
        '出库数量', '出库单价', '入库单价', # 添加入库单价列
        '仓库名', '仓库备注', '仓库地址', '操作者ID', '操作时间', '出库总价'
    ]
    FIELD_TYPES = {
        "出库单号": 1,  # 文本类型
        "出库日期": 5,  # 日期时间类型
        "快递单号": 1,  # 文本类型
        "快递手机号": 1,  # 文本类型
        "客户": 1,  # 文本类型
        "商品ID": 1,  # 文本类型
        "商品名称": 1,  # 文本类型
        "出库数量": 2,  # 数字类型
        "出库单价": 2,  # 数字类型
        "入库单价": 2,  # 数字类型
        "仓库名": 1,  # 文本类型
        "仓库备注": 1,  # 文本类型
        "仓库地址": 1,  # 文本类型
        "操作者ID": 11,  # 用户类型
        "操作时间": 5,  # 日期时间类型
        "出库总价": 2,  # 数字类型
    }

    def add_outbound(self, data_list: list[dict]) -> bool:
        """添加多条出库记录"""
        try:
            inventory_mgr = InventorySummaryManager()
            config = self.bitable_config[self.TABLE_NAME]
            successful_records = []

            outbound_no = f"OUT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            print(f"生成出库单号: {outbound_no}")

            # 首先检查所有商品的库存是否足够
            for data in data_list:
                try:
                    fields = data.get('fields', data)
                    product_id = fields.get('商品ID')
                    warehouse = fields.get('仓库名')
                    required_qty = float(fields.get('出库数量', 0))
                    
                    print(f"检查库存: 商品ID={product_id}, 仓库={warehouse}, 需要数量={required_qty}")
                    
                    # 获取当前库存
                    stock_df = inventory_mgr.get_stock_summary(product_id=product_id, warehouse=warehouse)
                    if stock_df.empty:
                        print(f"未找到库存记录: 商品ID={product_id}, 仓库={warehouse}")
                        return False
                    
                    total_stock = float(stock_df['当前库存'].sum())
                    print(f"当前库存: {total_stock}")
                    
                    # 如果库存不足，直接返回错误
                    if total_stock < required_qty:
                        print(f"商品 {fields.get('商品名称')} 库存不足: 需要 {required_qty}, 实际 {total_stock}")
                        return False
                    
                    # 检查出库数量是否有效
                    if required_qty <= 0:
                        print(f"出库数量无效: {required_qty}")
                        return False

                except (ValueError, TypeError) as e:
                    print(f"检查库存时发生错误: {e}")
                    return False

            # 所有库存检查通过后，开始处理出库
            try:
                for data in data_list:
                    fields = data.get('fields', data)
                    required_qty = float(fields.get('出库数量', 0))
                    product_id = fields.get('商品ID', '')
                    warehouse = fields.get('仓库名', '')

                    # 获取库存记录，按入库单价降序排序
                    stock_records = inventory_mgr.get_stock_summary(
                        product_id=product_id, 
                        warehouse=warehouse
                    ).sort_values('入库单价', ascending=False)

                    remaining_qty = required_qty
                    for _, stock in stock_records.iterrows():
                        if remaining_qty <= 0:
                            break

                        current_stock = float(stock['当前库存'])
                        if current_stock <= 0:
                            continue

                        outbound_qty = min(remaining_qty, current_stock)
                        
                        # 为每个不同入库单价创建一条出库记录
                        new_record = [{
                            "fields": {
                                "出库单号": outbound_no,
                                "出库日期": fields.get('出入库日期', ''),
                                "快递单号": fields.get('快递单号', ''),
                                "快递手机号": fields.get('快递手机号', ''),
                                "客户": fields.get('客户', ''),
                                "商品ID": product_id,
                                "商品名称": fields.get('商品名称', ''),
                                "出库数量": outbound_qty,
                                "出库单价": float(fields.get('出库单价', 0)),
                                "入库单价": float(stock['入库单价']),
                                "仓库名": warehouse,
                                "仓库备注": fields.get('仓库备注', ''),
                                "仓库地址": fields.get('仓库地址', ''),
                                "操作者ID": fields.get('操作者ID', ''),
                                "操作时间": fields.get('操作时间', ''),
                                "出库总价": outbound_qty * float(fields.get('出库单价', 0))
                            }
                        }]

                        print(f"准备写入出库记录: {new_record}")
                        
                        response = self.sheet_client.write_bitable(
                            app_token=config["app_token"],
                            table_id=config["table_id"],
                            records=new_record
                        )

                        if response:
                            # 更新库存汇总
                            outbound_data = {
                                "商品ID": product_id,
                                "商品名称": fields.get('商品名称', ''),
                                "仓库名": warehouse,
                                "出库数量": outbound_qty,
                                "出库单价": float(fields.get('出库单价', 0)),
                                "入库单价": float(stock['入库单价'])  # 添加入库单价
                            }
                            
                            if inventory_mgr.update_outbound(outbound_data):
                                successful_records.append({
                                    'record': new_record[0],
                                    'response': response
                                })
                                remaining_qty -= outbound_qty
                            else:
                                self._rollback_records(successful_records)
                                print("更新库存汇总失败")
                                return False
                        else:
                            self._rollback_records(successful_records)
                            print("写入出库记录失败")
                            return False

                    if remaining_qty > 0:
                        self._rollback_records(successful_records)
                        print(f"商品 {fields.get('商品名称')} 库存不足")
                        return False

                    print(f"成功处理商品 {fields.get('商品名称')} 的出库")

                return True

            except Exception as e:
                self._rollback_records(successful_records)
                print(f"处理出库记录时发生错误: {str(e)}")
                return False

        except Exception as e:
            print(f"添加出库记录时发生错误: {str(e)}")
            return False

    def _rollback_records(self, successful_records: list) -> None:
        """回滚已写入的记录"""
        try:
            config = self.bitable_config[self.TABLE_NAME]
            for record in successful_records:
                try:
                    record_id = record['response']['data']['records'][0]['record_id']
                    self.sheet_client.delete_bitable_records(
                        app_token=config["app_token"],
                        table_id=config["table_id"],
                        record_ids=[record_id]  # 需要传入列表
                    )
                    print(f"成功回滚记录: {record_id}")
                except Exception as e:
                    print(f"回滚记录时发生错误: {str(e)}")
        except Exception as e:
            print(f"回滚过程中发生错误: {str(e)}")

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

class InventorySummaryManager(BaseTableManager):
    TABLE_NAME = "inventory_summary"
    COLUMNS = [
        '商品ID', '商品名称', '仓库名', '入库单价', 
        '累计入库数量', '累计出库数量', '当前库存', 
        '入库总价', '出库总价', '最后更新时间',
        '最后入库时间', '最后出库时间'
    ]
    FIELD_TYPES = {
        "入库单价": 2,  # 数字类型
        "累计入库数量": 2,  # 数字类型
        "累计出库数量": 2,  # 数字类型
        "当前库存": 2,  # 数字类型
        "入库总价": 2,  # 数字类型
        "出库总价": 2,  # 数字类型
        "最后更新时间": 5,  # 日期时间类型
        "最后入库时间": 5,  # 日期时间类型
        "最后出库时间": 5,  # 日期时间类型
    }

    def update_inbound(self, inbound_data: dict) -> bool:
        """处理入库记录，更新库存汇总"""
        try:
            config = self.bitable_config[self.TABLE_NAME]
            
            # 打印调试信息
            print(f"更新库存汇总，入库数据: {inbound_data}")
            
            # 查找现有记录
            existing_data = self.sheet_client.read_bitable(
                app_token=config["app_token"],
                table_id=config["table_id"]
            )

            # 修改这里：使用入库单价和入库数量字段
            query_key = (
                inbound_data['商品ID'],
                inbound_data['仓库名'],
                float(inbound_data['入库单价'])  # 使用入库单价字段
            )

            # 查找匹配记录
            matching_record = None
            record_id = None
            
            if existing_data and existing_data.get("items"):
                for item in existing_data["items"]:
                    fields = item["fields"]
                    if (fields.get("商品ID") == query_key[0] and
                        fields.get("仓库名") == query_key[1] and
                        abs(float(fields.get("入库单价", 0)) - query_key[2]) < 0.01):  # 使用近似相等比较浮点数
                        matching_record = fields
                        record_id = item["record_id"]
                        break

            current_time = int(datetime.now().timestamp() * 1000)  # 使用毫秒级时间戳
            quantity = float(inbound_data['入库数量'])  # 使用入库数量字段
            price = float(inbound_data['入库单价'])    # 使用入库单价字段
            total_price = quantity * price

            # 打印调试信息
            print(f"处理数据: 数量={quantity}, 单价={price}, 总价={total_price}")
            print(f"匹配记录: {matching_record}")

            if matching_record:
                # 更新现有记录
                new_inbound_qty = float(matching_record.get('累计入库数量', 0)) + quantity
                new_current_qty = float(matching_record.get('当前库存', 0)) + quantity
                new_inbound_total = float(matching_record.get('入库总价', 0)) + total_price

                update_fields = {
                    "累计入库数量": new_inbound_qty,
                    "当前库存": new_current_qty,
                    "入库总价": new_inbound_total,
                    "最后更新时间": current_time,
                    "最后入库时间": current_time
                }

                print(f"更新字段: {update_fields}")

                response = self.sheet_client.update_bitable(
                    app_token=config["app_token"],
                    table_id=config["table_id"],
                    record_id=record_id,
                    fields=update_fields
                )
                if not response:
                    raise Exception("更新库存记录失败")
            else:
                # 创建新记录
                new_record = [{
                    "fields": {
                        "商品ID": inbound_data['商品ID'],
                        "商品名称": inbound_data['商品名称'],
                        "仓库名": inbound_data['仓库名'],
                        "入库单价": price,
                        "累计入库数量": quantity,
                        "累计出库数量": 0,
                        "当前库存": quantity,
                        "入库总价": total_price,
                        "出库总价": 0,
                        "最后更新时间": current_time,
                        "最后入库时间": current_time,
                        "最后出库时间": None
                    }
                }]

                print(f"新建记录: {new_record}")

                response = self.sheet_client.write_bitable(
                    app_token=config["app_token"],
                    table_id=config["table_id"],
                    records=new_record
                )
                if not response:
                    raise Exception("创建库存记录失败")

            return True

        except Exception as e:
            print(f"更新入库库存汇总失败: {str(e)}")
            return False

    def update_outbound(self, outbound_data: dict) -> bool:
        """处理出库记录，更新库存汇总（优先出库价格高的商品）"""
        try:
            config = self.bitable_config[self.TABLE_NAME]
            
            # 查找该商品在指定仓库的所有库存记录
            existing_data = self.sheet_client.read_bitable(
                app_token=config["app_token"],
                table_id=config["table_id"]
            )

            if not existing_data or not existing_data.get("items"):
                raise Exception("未找到库存记录")

            # 筛选符合条件的记录并按入库单价降序排序
            matching_records = []
            for item in existing_data["items"]:
                fields = item["fields"]
                if (fields.get("商品ID") == outbound_data['商品ID'] and
                    fields.get("仓库名") == outbound_data['仓库名'] and
                    float(fields.get("当前库存", 0)) > 0):
                    matching_records.append({
                        "record_id": item["record_id"],
                        "fields": fields
                    })

            if not matching_records:
                raise Exception("没有足够的库存")

            # 按入库单价降序排序
            matching_records.sort(
                key=lambda x: float(x["fields"].get("入库单价", 0)), 
                reverse=True
            )

            # 计算需要出库的数量
            remaining_qty = float(outbound_data['出库数量'])  # 修改这里：使用出库数量
            current_time = int(datetime.now().timestamp() * 1000)  # 使用毫秒级时间戳

            # 从高价库存开始出库
            for record in matching_records:
                if remaining_qty <= 0:
                    break

                current_stock = float(record["fields"].get("当前库存", 0))
                outbound_qty = min(remaining_qty, current_stock)
                outbound_price = float(outbound_data['出库单价'])  # 修改这里：使用出库单价
                total_price = outbound_qty * outbound_price

                # 更新记录
                new_outbound_qty = float(record["fields"].get("累计出库数量", 0)) + outbound_qty
                new_current_qty = current_stock - outbound_qty
                new_outbound_total = float(record["fields"].get("出库总价", 0)) + total_price

                update_fields = {
                    "累计出库数量": new_outbound_qty,
                    "当前库存": new_current_qty,
                    "出库总价": new_outbound_total,
                    "最后更新时间": current_time,
                    "最后出库时间": current_time
                }

                self.sheet_client.update_bitable(
                    app_token=config["app_token"],
                    table_id=config["table_id"],
                    record_id=record["record_id"],
                    fields=update_fields
                )

                remaining_qty -= outbound_qty

            if remaining_qty > 0:
                raise Exception("库存不足")

            return True

        except Exception as e:
            print(f"更新出库库存汇总失败: {e}")
            return False

    def get_stock_summary(self, product_id: str = None, warehouse: str = None) -> pd.DataFrame:
        """获取库存汇总信息"""
        try:
            config = self.bitable_config[self.TABLE_NAME]
            data = self.sheet_client.read_bitable(
                app_token=config["app_token"],
                table_id=config["table_id"]
            )
            
            if not data or not data.get("items"):
                return pd.DataFrame(columns=self.COLUMNS)
            
            records = []
            for item in data["items"]:
                fields = item["fields"]
                if (product_id and fields.get("商品ID") != product_id or
                    warehouse and fields.get("仓库名") != warehouse):
                    continue
                    
                records.append([
                    fields.get(col, "") for col in self.COLUMNS
                ])
            
            return pd.DataFrame(records, columns=self.COLUMNS)
            
        except Exception as e:
            print(f"获取库存汇总失败: {e}")
            return pd.DataFrame()

def test_inventory_operations():
    """测试入库和出库操作"""
    try:
        # 初始化管理器
        inbound_mgr = InboundManager()
        outbound_mgr = OutboundManager()
        inventory_mgr = InventorySummaryManager()

        # 测试数据 - 入库
        current_timestamp = int(datetime.now().timestamp() * 1000)  # 转换为毫秒级时间戳
        test_user_id = "ou_8234c13164697b3c129c84a14f36386f"  # 使用实际的用户ID
        inbound_data = [
            {
                "入库单号": "TEST-IN-002",
                "入库日期": current_timestamp,  # 使用时间戳
                "快递单号": "SF001",
                "快递手机号": "13800138000",
                "供应商": "测试供应商A",
                "商品ID": "TEST-P001",
                "商品名称": "测试商品1",
                "数量": 100,
                "单价": 10.5,
                "仓库名": "测试仓库",
                "仓库备注": "测试用",
                "仓库地址": "测试地址",
                "操作者ID": [{"id": test_user_id}],
                "操作时间": current_timestamp  # 使用时间戳
            },
            {
                "入库单号": "TEST-IN-002",
                "入库日期": current_timestamp,  # 使用时间戳
                "快递单号": "SF001",
                "快递手机号": "13800138000",
                "供应商": "测试供应商A",
                "商品ID": "TEST-P001",  # 同一商品，不同价格
                "商品名称": "测试商品1",
                "数量": 50,
                "单价": 12.0,
                "仓库名": "测试仓库",
                "仓库备注": "测试用",
                "仓库地址": "测试地址",
                "操作者ID": [{"id": test_user_id}],
                "操作时间": current_timestamp  # 使用时间戳
            }
        ]

        print("\n=== 测试入库操作 ===")
        inbound_result = inbound_mgr.add_inbound(inbound_data)
        print(f"入库结果: {'成功' if inbound_result else '失败'}")

        # 查看入库后的库存状态
        print("\n=== 入库后库存状态 ===")
        stock_after_inbound = inventory_mgr.get_stock_summary(product_id="TEST-P001")
        print(stock_after_inbound)

        # 测试数据 - 出库
        outbound_data = [
            {
                "出库单号": "TEST-OUT-002",
                "出库日期": current_timestamp,  # 使用时间戳
                "快递单号": "SF002",
                "快递手机号": "13900139000",
                "客户": "测试客户A",
                "商品ID": "TEST-P001",
                "商品名称": "测试商品1",
                "数量": 80,  # 部分出库
                "单价": 15.0,
                "仓库名": "测试仓库",
                "仓库备注": "测试用",
                "仓库地址": "测试地址",
                "操作者ID": [{"id": test_user_id}],
                "操作时间": current_timestamp  # 使用时间戳
            }
        ]

        print("\n=== 测试出库操作 ===")
        outbound_result = outbound_mgr.add_outbound(outbound_data)
        print(f"出库结果: {'成功' if outbound_result else '失败'}")

        # 查看出库后的库存状态
        print("\n=== 出库后库存状态 ===")
        stock_after_outbound = inventory_mgr.get_stock_summary(product_id="TEST-P001")
        print(stock_after_outbound)

        # 测试库存不足的情况
        print("\n=== 测试库存不足情况 ===")
        outbound_data_insufficient = [
            {
                "出库单号": "TEST-OUT-003",
                "出库日期": current_timestamp,  # 使用时间戳
                "快递单号": "SF003",
                "快递手机号": "13900139000",
                "客户": "测试客户B",
                "商品ID": "TEST-P001",
                "商品名称": "测试商品1",
                "数量": 20,  # 超出库存数量
                "单价": 15.0,
                "仓库名": "测试仓库",
                "仓库备注": "测试用",
                "仓库地址": "测试地址",
                "操作者ID": [{"id": test_user_id}],
                "操作时间": current_timestamp  # 使用时间戳
            }
        ]
        outbound_result = outbound_mgr.add_outbound(outbound_data_insufficient)
        print(f"库存不足出库结果: {'成功' if outbound_result else '失败'}")

    except Exception as e:
        print(f"测试过程中发生错误: {e}")

if __name__ == "__main__":
    test_inventory_operations()


