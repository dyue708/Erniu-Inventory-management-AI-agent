# 库存管理系统

基于飞书表格的智能库存管理系统，集成了深度求索 AI 对话功能。

## 功能特点

- 基于飞书表格的库存数据管理
- 支持商品、仓库、分类等基础信息管理
- 集成深度求索 AI，支持智能对话查询
- 实时消息通知和处理

## 安装

1. 克隆项目
2. 创建虚拟环境：`python -m venv venv`
3. 激活虚拟环境：
   - Windows: `venv\Scripts\activate`
   - Linux/Mac: `source venv/bin/activate`
4. 安装依赖：`pip install -r requirements.txt`
5. 配置环境变量：
   - 复制 `.env.sample` 为 `.env`
   - 配置飞书应用信息(APP_ID、APP_SECRET等)
   - 配置飞书表格信息(各表格ID和TOKEN)
   - 配置深度求索API信息(API_KEY等)

## 使用

1. 确保已配置:
   - 飞书应用权限
   - 飞书表格访问权限
   - 深度求索API访问权限
2. 运行程序：`python src/main_run.py`
3. 程序会启动两个服务:
   - 消息存储服务
   - 消息处理服务