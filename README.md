# 库存管理系统

基于飞书表格的智能库存管理系统，集成了深度求索 AI 对话功能。

## 系统特性

- 📊 基于飞书表格的库存数据管理
- 📦 支持商品、仓库、分类等基础信息管理
- 🤖 集成深度求索 AI，支持智能对话查询
- ⚡ 实时消息通知和处理

## 配置指南

### 1. 飞书配置

#### 1.1 基础准备
- 下载并安装[飞书](https://www.feishu.cn/)客户端
- 创建新组织或加入已有组织（需要管理员权限）

#### 1.2 应用创建
1. 访问[飞书开放平台](https://open.feishu.cn/)创建应用
2. 获取 APP_ID 和 APP_SECRET
3. 开启机器人功能

#### 1.3 权限配置
必需权限：
- im:message
- im:message.group_at_msg
- im:message.p2p_msg
- sheet:read
- sheet:write
- im:resource
- im:chat
- im:chat.member

#### 1.4 事件订阅
1. 配置 Webhook URL（运行 message_store_bot.py 后获取）
2. 设置验证 token 和加密 key
3. 订阅以下事件：
   - im.message.receive_v1
   - im.chat.member.bot.added_v1
   - im.chat.member.bot.deleted_v1

#### 1.5 飞书表格准备
创建并配置以下表格：
- 商品信息表(products)
- 仓库信息表(warehouses)
- 库存记录表(inventory)

> 📝 **表格链接说明**  
> 示例链接：https://example.feishu.cn/base/xxxxxxxxxxxxxxxxxxxxxx/table/tblxxxxxxxxxxxxxx
> - `xxxxxxxxxxxxxxxxxxxxxx` = app_token
> - `tblxxxxxxxxxxxxxx` = table_id
#### 1.6 添加应用到表格
1. 打开飞书多维表格
2. 点击右上角"添加应用"按钮
3. 在弹出窗口中搜索并选择你创建的应用
4. 确认授权

![添加应用到表格](image/add-app-to-sheet.png)

> ⚠️ **注意**：必须将应用添加到所有相关表格中，否则机器人将无法读写数据


### 2. Deepseek 配置

1. 访问 [Deepseek 开放平台](https://platform.deepseek.com/) 注册账号
2. 在开发者控制台创建并保存 API Key

## 部署指南

### 1. 环境准备
```bash
# 克隆项目
git clone <项目地址>

# 创建并激活虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 环境配置
1. 复制 `.env.sample` 为 `.env`
2. 配置以下环境变量：
```
FEISHU_APP_ID=cli_a7******76100d
FEISHU_APP_SECRET=BZYg***********************pjGG
FEISHU_SHEET_TOKEN=GYw9s*************6cKgnYn5e
WAREHOUSE_SHEET_ID=ad8f**
PRODUCT_SHEET_ID=8Fis**
CATEGORY_SHEET_ID=tt7Q**
INVENTORY_SHEET_ID=aX0S**
FEISHU_VERIFICATION_TOKEN=eCBE********************Wgd4
FEISHU_ENCRYPT_KEY=cMt1******************6voTyf
DEEPSEEK_API_KEY=sk-6d0*********************004a
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL="deepseek-chat"
```

## 启动服务

1. 启动前检查：
   - ✅ 飞书应用状态（已上线或测试状态）
   - ✅ 机器人已添加到目标群组
   - ✅ 表格权限配置完成
   - ✅ Deepseek API 配置有效

2. 运行服务：
```bash
python run.py
```

服务将启动：
- 消息存储服务：接收并存储飞书消息
- 消息处理服务：处理库存相关指令