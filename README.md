# 二牛库存管理AI助手

基于飞书表格的智能库存管理系统，集成了深度求索 AI 对话功能。
实现纯自然语言对话，无需记忆命令，即可完成商品出入库操作。

## 系统特性
- 🖥️ 本地运行程序，无需服务器和域名
- 💰 唯一成本为按量使用的AI接口调用费用（Deepseek）
- 🃏 支持通过飞书卡片提交出入库操作
- 👥 适合小团队协作管理商品出入库，以及商品库存管理
- 📊 基于飞书表格进行库存数据管理
- 🛠️ 可自定义飞书多维表格的可视化拓展，自定义仪表盘等
- 📦 支持商品、仓库、分类等基础信息管理
- 🤖 集成深度求索 AI，支持对话入库出库操作
- ⚡ 基于飞书机器人的实时消息通知和处理
- 📈 支持商品出入库管理，出库时实时计算单笔利润
- 📉 同一商品不同入库价格时，默认逻辑：出库时优先算出库入库单价高的商品
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
权限配置：
```json
{
  "scopes": {
    "tenant": [
      "aily:message:write",
      "base:app:update",
      "base:table:create",
      "base:table:read",
      "base:table:update",
      "bitable:app",
      "cardkit:card:write",
      "im:chat",
      "im:message",
      "im:message.group_at_msg:readonly",
      "im:message.group_msg",
      "im:message.p2p_msg:readonly",
      "im:message:readonly"
    ],
    "user": [
      "aily:message:write",
      "base:app:update",
      "base:table:create",
      "base:table:read",
      "base:table:update",
      "bitable:app",
      "im:chat",
      "im:message",
      "im:message:readonly"
    ]
  }
}
```

#### 1.4 事件订阅
1. 配置 Webhook URL
https://open.feishu.cn/api-explorer/loading 
或者运行 message_store_bot.py 后获取  使用长链接接收事件
2. 设置验证 token 和加密 key
3. 订阅以下事件：
   - im.message.receive_v1
   - application.bot.menu_v6

4. 订阅卡片交互回调
   - card.action.trigger


#### 1.5 飞书表格准备
创建并配置以下表格：
可使用模板
https://ccn1hpzj4iz4.feishu.cn/base/DyAYb1D2RaYcbQsjdsdcZOEOnad?table=tblZiGbWquMGu3jB&view=vewHk4ASHw
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


#### 1.7 飞书卡片交互功能
增加了飞书卡片交互功能，可以实现更加复杂的交互操作。需要使用飞书机器人菜单功能，并添加菜单事件处理器。

##### 事件处理器：
- **INBOUND**: 获取入库表单
- **OUTBOUND**: 获取出库表单
![添加机器人菜单订阅](image/bot_menu.png)

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
1. 复制 `.env.example` 为 `.env`
2. 配置以下环境变量：
```
# 飞书应用配置
FEISHU_APP_ID=cli_a7******76100d
FEISHU_APP_SECRET=BZYg***********************pjGG
FEISHU_VERIFICATION_TOKEN=eCBE********************Wgd4
FEISHU_ENCRYPT_KEY=cMt1******************6voTyf

# 飞书表格配置
FEISHU_SHEET_TOKEN=GYw9s*************6cKgnYn5e
WAREHOUSE_SHEET_ID=ad8f**
PRODUCT_SHEET_ID=8Fis**
CATEGORY_SHEET_ID=tt7Q**
INVENTORY_SHEET_ID=aX0S**

# Deepseek 配置
DEEPSEEK_API_KEY=sk-6d0*********************004a
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL="deepseek-chat"
```

## 启动服务

1. 启动前检查：
   - ✅ 飞书应用状态（已上线或测试状态）
   - ✅ 表格权限配置完成
   - ✅ Deepseek API 配置有效
   - ✅ 飞书机器人已添加到目标群组

2.根据自己的需要配置商品表 以及 仓库管理表信息

3. 运行服务：
```bash
python run.py
```

服务将启动：
- 消息存储服务：接收并存储飞书消息
- 消息处理服务：处理库存相关指令

发送消息到飞书群组，或者私聊对应机器人，即可触发机器人处理库存相关指令
也可以在机器人私聊界面获取 入库 以及 出库表单 完成入库 出库操作




