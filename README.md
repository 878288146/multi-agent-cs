# 智能客服多Agent系统

基于 LangGraph 的多 Agent 协同智能客服系统，支持意图识别、RAG 知识检索、工单处理、合规审查、天气查询等功能。

## 系统架构

```
用户 (Web/App/API)
        │
        ▼
┌──────────────────────┐
│   API Gateway        │
│   (FastAPI)          │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│              Supervisor 编排 Agent                │
│  ┌─────────────┐         ┌────────────────────┐  │
│  │  分层记忆系统  │         │  全链路追踪          │  │
│  │ • 工作记忆    │         │  (OpenTelemetry)   │  │
│  │ • 短期(Redis) │         │  Agent调用链可视化  │  │
│  │ • 长期(向量库) │         └────────────────────┘  │
│  └─────────────┘                                  │
└──────┬──────────┬──────────┬──────────┬───────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
  ┌─────────┐┌─────────┐┌─────────┐┌─────────┐
  │ 意图路由  ││ 知识检索  ││ 工单处理  ││ 天气查询  │
  │  Agent   ││  Agent   ││  Agent   ││  Agent   │
  └─────────┘└─────────┘└─────────┘└─────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
  ┌─────────────────────────────────────────────┐
  │           合规审查 Agent                      │
  │  规则引擎(<2ms) + LLM审查(~600ms) 双重检测    │
  └─────────────────────────────────────────────┘
```

## 核心功能

### 1. Supervisor 编排模式
- Supervisor 统一调度，子 Agent 各司其职
- 支持 Human-in-the-Loop 断点暂停
- LangGraph Checkpoint 对话中断续接

### 2. 分层记忆系统
| 记忆层 | 存储 | TTL | 用途 |
|--------|------|-----|------|
| 工作记忆 | 进程内存 | 单次请求 | 当前推理状态 |
| 短期记忆 | Redis | 30分钟 | 多轮对话上下文 |
| 长期记忆 | FAISS 向量库 | 永久 | 知识库、用户画像 |

### 3. Agent 能力
- **意图路由** — 用户意图识别与实体提取
- **RAG 知识检索** — Query 改写 → 向量检索 → 重排序 → LLM 生成
- **工单处理** — 创建/查询工单，支持退款/投诉/开户等类型
- **天气查询** — 实时天气，景点→城市映射，不明确时反问用户
- **合规审查** — 敏感词/PII 检测 + LLM 深度合规审查

### 4. MCP 工具协议
- `order_query` — 订单查询
- `knowledge_search` — 知识库搜索
- `ticket_create` — 工单创建
- `risk_check` — 风控检查
- `weather_query` — 天气查询

### 5. 全链路追踪 (OpenTelemetry)
- 每个 Agent 调用生成独立 Span
- Token 消耗和耗时追踪

## 技术栈

| 层次 | 选型 |
|------|------|
| **AI框架** | LangGraph |
| **LLM** | GPT-4o / Claude / MiniMax |
| **向量数据库** | FAISS |
| **缓存** | Redis |
| **追踪** | OpenTelemetry + Jaeger |
| **API** | FastAPI |
| **前端** | Vue 3 + naive-ui |
| **容器** | Docker + Docker Compose |

## 快速开始

### 前置条件
- Python 3.11+
- OpenAI API Key（或其他 LLM Key）

### 直接运行

```bash
cd python-impl

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填写 OPENAI_API_KEY

# 启动服务
python api/main.py

# 测试
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "北京天气怎么样"}'
```

### Docker 启动

```bash
docker-compose up -d
```

### 前端启动

```bash
cd web
npm install
npm run dev
```

## 项目结构

```
smart-cs-multi-agent/
│
├── python-impl/              # Python 后端
│   ├── agents/               # Agent 核心 (supervisor / intent_router / knowledge_rag / ticket_handler / compliance_checker / weather)
│   ├── api/                  # FastAPI 接口
│   ├── mcp/                  # MCP 工具协议
│   ├── memory/               # 三层记忆系统
│   ├── tracing/              # OpenTelemetry 追踪
│   └── requirements.txt
│
├── web/                      # Vue 3 前端
│   └── src/
│       ├── App.vue           # 聊天界面
│       └── config.ts         # API 配置
│
├── docs/                     # 文档
│   ├── architecture.md       # 架构设计
│   ├── code-walkthrough.md   # 核心代码解析
│   └── deployment.md         # 部署指南
│
├── docker-compose.yml
└── README.md
```

## 请求处理流程

```
用户消息 → Supervisor 路由决策
  ├─ greeting       → 直接问候
  ├─ knowledge_rag  → RAG 知识检索
  ├─ ticket_handler → 工单处理
  ├─ weather        → 天气查询
  └─ (默认)         → knowledge_rag
         ↓
      合规审查 → 汇总 → 返回
```

## 服务地址

| 服务 | 地址 |
|------|------|
| 后端 API | `http://localhost:8000` |
| API 文档 | `http://localhost:8000/docs` |
| 前端 | `http://localhost:3000` |

## 安全说明

- 本项目不包含任何真实 API Key
- 所有敏感配置通过环境变量注入
- 请勿将 `.env` 文件提交到版本控制
