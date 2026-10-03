# Agent-Harness 多模态智能体平台

基于 **Agent-Harness 分层架构** 的多智能体 AI 平台，支持多智能体对话、RAG 文档问答与 Markdown 文档生成。

## 架构分层

| 层级 | 职责 | 目录 |
|------|------|------|
| Harness | 编排 (LangGraph StateGraph + Supervisor 路由 + 生命周期) | `backend/app/harness/` |
| Agent | 思考 (RAG / Vision / Coder / Writer 四专家) | `backend/app/agents/` |
| Tool/Sandbox | 执行 (E2B 沙箱, 禁 exec) | `backend/app/tools/` |
| Memory | 记忆 (AsyncSqliteSaver + ChromaDB) | `backend/app/memory/` |
| Model | 模型 (统一工厂: 云端 OpenAI 兼容 + 本地 Ollama) | `backend/app/llm/` |

## 技术栈

- **前端**: Vue 3 + Vite + TypeScript + Tailwind CSS + shadcn-vue
- **后端**: Python 3.12 (conda `graph312`) + FastAPI + Pydantic V2
- **AI**: LangChain + LangGraph + LangChain-OpenAI + LangChain-Ollama
- **沙箱**: e2b-code-interpreter (Docker 备选)
- **向量**: ChromaDB
- **数据库**: SQLite(async) 开发 / PostgreSQL 生产

## 快速开始

```bash
# 后端 (conda graph312)
cd backend
conda run -n graph312 pip install -r requirements.txt
conda run -n graph312 uvicorn app.main:app --reload

# 前端 (Phase 4)
cd frontend
npm install
npm run dev
```

接口文档: http://localhost:8000/docs

## 开发阶段

- [x] Phase 1: 项目骨架 + FastAPI + 认证 + 模型 + SSE
- [ ] Phase 2: Agent-Harness 核心 + 多智能体
- [ ] Phase 3: RAG 文档管理
- [ ] Phase 4: 前端完整实现
- [ ] Phase 5: 多用户隔离 + 联调 + 优化
