import os
import sys

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

import logging
from src.config import FEISHU_CONFIG
from src.feishu_sheet import FeishuSheet
from src.table_manage import InboundManager, OutboundManager, InventorySummaryManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def clear_table(sheet_client, app_token, table_id, table_name):
    """清空指定表的所有数据，但保留表头"""
    try:
        # 获取表中所有记录
        data = sheet_client.read_bitable(
            app_token=app_token,
            table_id=table_id
        )
        
        if not data or not data.get("items"):
            logger.info(f"表 {table_name} 中没有数据需要清空")
            return True
        
        # 收集所有记录ID
        record_ids = [item["record_id"] for item in data["items"]]
        
        # 批量删除记录
        if record_ids:
            logger.info(f"正在删除 {table_name} 表中的 {len(record_ids)} 条记录...")
            
            # 由于API可能有批量限制，分批删除
            batch_size = 100
            for i in range(0, len(record_ids), batch_size):
                batch_ids = record_ids[i:i+batch_size]
                response = sheet_client.delete_bitable_records(
                    app_token=app_token,
                    table_id=table_id,
                    record_ids=batch_ids
                )
                if not response:
                    logger.error(f"删除 {table_name} 表中的部分记录失败")
                    return False
                
                logger.info(f"已删除 {len(batch_ids)} 条记录")
            
            logger.info(f"成功清空 {table_name} 表中的所有数据")
            return True
        
        return True
    
    except Exception as e:
        logger.error(f"清空 {table_name} 表时发生错误: {e}", exc_info=True)
        return False

def main():
    """清空入库明细、出库明细和库存汇总表"""
    try:
        # 初始化飞书API客户端
        sheet_client = FeishuSheet(
            app_id=FEISHU_CONFIG["APP_ID"],
            app_secret=FEISHU_CONFIG["APP_SECRET"]
        )
        
        # 初始化表管理器
        inbound_mgr = InboundManager()
        outbound_mgr = OutboundManager()
        inventory_mgr = InventorySummaryManager()
        
        # 获取表配置
        inbound_config = inbound_mgr.bitable_config["inbound"]
        outbound_config = outbound_mgr.bitable_config["outbound"]
        inventory_config = inventory_mgr.bitable_config["inventory_summary"]
        
        logger.info("开始清空表数据...")
        
        # 清空入库明细表
        inbound_result = clear_table(
            sheet_client=sheet_client,
            app_token=inbound_config["app_token"],
            table_id=inbound_config["table_id"],
            table_name="入库明细表"
        )
        
        # 清空出库明细表
        outbound_result = clear_table(
            sheet_client=sheet_client,
            app_token=outbound_config["app_token"],
            table_id=outbound_config["table_id"],
            table_name="出库明细表"
        )
        
        # 清空库存汇总表
        inventory_result = clear_table(
            sheet_client=sheet_client,
            app_token=inventory_config["app_token"],
            table_id=inventory_config["table_id"],
            table_name="库存汇总表"
        )
        
        # 汇总结果
        if inbound_result and outbound_result and inventory_result:
            logger.info("所有表数据清空成功！")
        else:
            logger.warning("部分表数据清空失败，请检查日志")
            
    except Exception as e:
        logger.error(f"清空表数据过程中发生错误: {e}", exc_info=True)

if __name__ == "__main__":
    main() 