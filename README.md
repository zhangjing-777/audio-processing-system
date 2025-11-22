# 音频处理后端 - 完整版

## 项目说明

这是一个完整的音频处理后端项目，集成了用户系统、计费功能和三种音频处理服务。

## 功能特性

### 音频处理服务
1. **钢琴扒谱 (PianoTrans)** - 将音频转换为MIDI
2. **音频分离 (Spleeter)** - 分离人声、伴奏（支持2/4/5轨）
3. **多轨扒谱 (YourMT3)** - 多乐器MIDI提取

### 用户系统
- 基于 Supabase Auth 的用户认证
- JWT token 验证
- 用户等级系统 (Free/Pro)
- 邀请码升级功能

### 计费系统
- 分级定价（Pro用户享受75折）
- 按音频时长计费（每3分钟为一个计费单位）
- 自动扣费（处理成功才扣费）
- 余额查询和充值

### 缓存机制
- 文件级缓存（相同文件不重复处理）
- 智能去重（基于文件哈希）

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填写配置：

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的配置
```

**重要配置项**：
- AWS S3 凭证
- Supabase URL 和 Keys
- JWT Secret (从 Supabase 获取)
- RunPod API Keys 和 Endpoints
- 数据库连接信息

### 3. 初始化数据库

```bash
python scripts/init_database.py
```

### 4. 初始化数据 (定价和邀请码)

```bash
python scripts/init_data.py
```

### 5. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API 文档

启动服务后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 主要 API 端点

### 用户相关
- `GET /api/user/me` - 获取当前用户信息
- `GET /api/user/credits` - 查询余额
- `POST /api/user/use-invite-code` - 使用邀请码升级

### 音频处理
- `POST /api/piano/transcribe` - 钢琴扒谱
- `POST /api/spleeter/separate` - 音频分离
- `POST /api/yourmt3/transcribe` - 多轨扒谱

### 历史记录
- `GET /api/processing/history` - 处理历史
- `GET /api/processing/{id}` - 查询处理进度

### 充值相关
- `POST /api/recharge/stripe/create-session` - Stripe充值
- `POST /api/recharge/wechat/create-order` - 微信充值
- `GET /api/recharge/history` - 充值历史

### 消费相关
- `GET /api/consumption/history` - 消费历史
- `GET /api/consumption/summary` - 消费统计

## 使用示例

### 1. 获取用户信息

```bash
curl -H "Authorization: Bearer YOUR_SUPABASE_JWT_TOKEN" \
  http://localhost:8000/api/user/me
```

### 2. 使用邀请码升级为Pro

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"code": "PRO2024"}' \
  http://localhost:8000/api/user/use-invite-code
```

### 3. 钢琴扒谱

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@music.mp3" \
  http://localhost:8000/api/piano/transcribe
```

### 4. 音频分离 (2轨)

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@music.mp3" \
  -F "stems=2" \
  http://localhost:8000/api/spleeter/separate
```

## 定价说明

### Piano Transcription
- Free用户: 2 credits / 3分钟
- Pro用户: 1.5 credits / 3分钟

### Spleeter
- Free用户: 3 credits / 3分钟
- Pro用户: 2.25 credits / 3分钟

### YourMT3
- Free用户: 4 credits / 3分钟
- Pro用户: 3 credits / 3分钟

## 项目结构

```
complete-audio-backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # 主应用入口
│   ├── config.py               # 配置管理
│   ├── database.py             # 数据库连接
│   ├── models.py               # 数据库模型
│   ├── schemas.py              # 原有schemas
│   ├── schemas_user.py         # 用户相关schemas
│   ├── auth/                   # 认证模块
│   │   ├── __init__.py
│   │   ├── dependencies.py     # JWT认证依赖
│   │   └── supabase_client.py  # Supabase客户端
│   ├── services/               # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── s3_service.py       # S3服务
│   │   ├── piano_service.py    # 钢琴扒谱服务
│   │   ├── spleeter_service.py # 音频分离服务
│   │   ├── yourmt3_service.py  # 多轨扒谱服务
│   │   ├── billing_service.py  # 计费服务
│   │   ├── user_service.py     # 用户服务
│   │   ├── invite_service.py   # 邀请码服务
│   │   ├── sync_service.py     # 用户同步服务
│   │   └── audio_utils.py      # 音频工具
│   ├── routers/                # API路由
│   │   ├── __init__.py
│   │   ├── piano.py            # 钢琴扒谱路由（已集成计费）
│   │   ├── spleeter.py         # 音频分离路由（已集成计费）
│   │   ├── yourmt3.py          # 多轨扒谱路由（已集成计费）
│   │   ├── user.py             # 用户路由
│   │   ├── recharge.py         # 充值路由
│   │   ├── consumption.py      # 消费记录路由
│   │   └── processing.py       # 处理历史路由
│   └── tasks/                  # 定时任务
│       └── sync_users.py       # 用户同步任务
├── scripts/                    # 初始化脚本
│   ├── init_database.py        # 初始化数据库
│   └── init_data.py            # 初始化数据
├── requirements.txt            # Python依赖
├── .env.example                # 环境变量示例
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── README.md
```