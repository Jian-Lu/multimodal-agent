# MCP 集成

所属层级: **MCP Infrastructure**

Agent-Harness 对 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 的集成。官方 Python SDK `mcp>=1.0.0`。

## 设计哲学(本阶段: 极简集成)

本模块遵循**极简集成**原则, 不做以下内容:

- ❌ 独立的 MCP Agent 节点(已移除 `mcp_agent.py` / `prompt.py`)
- ❌ 管理面板 / CRUD API / 多 Server 动态管理
- ❌ Supervisor 特殊路由表

只做一件事: **一个 MCP Server 在启动时连接一次, 把它的工具转成 LangChain `StructuredTool`, 绑定到现有 Agent**(默认回退 Agent: RAG)。

优点: 未启用 / 连接失败时自动降级为空工具列表, 现有 Agent 行为完全不受影响。

## 目录结构

| 文件 | 职责 | 状态 |
|------|------|------|
| `github_client.py` | **极简集成的唯一入口** — 连接 GitHub MCP Server(stdio)并产出 `StructuredTool` | 🆕 本阶段新增 |
| `manager.py` | `McpClientManager` 多 Server 会话生命周期 + 结果缓存 + 重连 | 底层复用 |
| `transports.py` | stdio / sse / streamable_http 传输层 (`mcp_client_session`) | 底层复用 |
| `tool_converter.py` | MCP Tool → LangChain `StructuredTool` + JSON Schema → Pydantic | 底层复用 |
| `schema.py` | `McpServerConfig` 数据模型(字段校验 + id/transport 归一化) | 底层复用 |
| `crypto.py` | 敏感字段(env/headers)Fernet 加密 | 底层复用 |
| `config.py` | 全局配置(`MCP_*` 环境变量 + `MCP_SERVER_*` 预配置) | 底层复用 |
| `__init__.py` | 包导出 | — |

## 数据流

```
main.py lifespan
  └─ init_github_mcp() ................. 启动时连接一次
       └─ McpClientManager.connect(cfg)   [McpServerConfig: stdio + npx server-github]
            └─ list_tools()               [发现工具]
                 └─ mcp_tool_to_langchain(server_id, tool, call_fn)
                      └─ StructuredTool(name="mcp_github_*")

RagAgent.run()
  ├─ get_github_mcp_tools() ........... 空列表 → 纯 RAG, 不触达 MCP
  └─ run_react_loop(llm, prompt, tools)  [ReAct 工具循环]
       ├─ llm.bind_tools(tools)
       ├─ ainvoke → tool_calls
       │    └─ tool.ainvoke(args) → Manager.call_tool(server, tool, args)
       ├─ ToolMessage 回填
       └─ 重复直到无 tool_calls / 深度上限
```

## 核心 API

### 极简集成入口(`github_client.py`)

| 函数 | 签名 | 说明 |
|------|------|------|
| `github_server_config()` | `() -> Optional[McpServerConfig]` | 从 `.env` 读 `MCP_GITHUB_*` 生成配置; 未启用返回 `None`; token 注入为 `GITHUB_PERSONAL_ACCESS_TOKEN` |
| `init_github_mcp()` | `async () -> list[McpToolInfo]` | 启动时连接一次 + 发现工具; 连接失败降级为 `[]` |
| `get_github_mcp_tools()` | `() -> list[StructuredTool]` | 返回已转换的工具; 未连接返回 `[]` |
| `shutdown_github_mcp()` | `async () -> None` | 关闭时断开连接 |

工具命名: `mcp_{server_id}_{tool_name}` → `mcp_github_*`。

### 底层能力(`manager.py`)

- `McpClientManager`: `connect(cfg)` / `connect_many(configs)` / `disconnect(server_id)` / `disconnect_all()` / `is_connected()` / `get_client()` / `list_connected()` / `get_all_tools()` / `get_all_langchain_tools()` / `call_tool(server_id, tool_name, args)`
- 结果缓存: 按工具+参数哈希缓存 300s(默认, 可用 `MCP_TOOL_CACHE_TTL` 覆盖)
- `McpToolInfo`: `server_id / server_name / name / original_name / description / input_schema`
- `McpError`: `{"error": "mcp_error", "server_id", "detail"}`
- 单例: `get_mcp_manager()`

### 工具转换(`tool_converter.py`)

`mcp_tool_to_langchain(server_id, tool, call_fn)` → `StructuredTool`(同步 `_call` 自动桥接 asyncio, 异步 `_acall` 直通); `json_schema_to_pydantic(input_schema, name)` 把 JSON Schema 转 Pydantic 参数模型(required 字段必填, 否则带默认值)。

## Agent 侧接入(本阶段新增)

| 文件 | 改动 |
|------|------|
| `agents/base.py` | 新增 `run_react_loop(llm, messages, tools, max_depth=5)` — 无工具时退化为 `astream_text`; 工具缺失/执行失败把错误写入 `ToolMessage`, 不中断 Agent; 超深度返回兜底文本 |
| `agents/rag.py` | 构造器加 `llm` 参数(测试注入); `run()` 取 `get_github_mcp_tools()`, 有工具时追加提示 "你可以调用 mcp_github_* 工具查询仓库、issue、PR 等信息" 并走 ReAct 循环 |
| `harness/supervisor.py` | 新增 `GITHUB_KEYWORDS`(`github`/`issue`/`repo`/`仓库`)→ `rag`, 位于代码意图之后、搜索意图之前 — 使「查一下 github …」直达拥有工具的 RAG |

## 生命周期

`backend/app/main.py` lifespan:

```python
await init_github_mcp()      # 启动: 连接一次
yield
await shutdown_github_mcp()  # 关闭: 断开
```

旧的 `_init_mcp_servers()`(数据库 + `MCP_SERVER_*` 多 Server 自动发现)已移除; `McpServerRecord` 模型与 `mcp_servers` 表保留(dormant), 不做 DB 迁移。

## .env 配置

```env
# 极简集成: GitHub MCP Server(stdio)
MCP_GITHUB_ENABLED=true
MCP_GITHUB_COMMAND=npx
MCP_GITHUB_ARGS=-y,@modelcontextprotocol/server-github
MCP_GITHUB_TOKEN=ghp_xxx
```

底层可选(见 `config.py`):

```env
MCP_ENCRYPTION_KEY=            # 未设时用 data/.mcp_enc_key, 再自动生成
MCP_TOOL_CACHE_TTL=300
MCP_MAX_CALL_DEPTH=5
```

## 测试

| 文件 | 覆盖 |
|------|------|
| `tests/test_github_client.py`(本阶段新增, 5 个) | 配置解析、未启用/未连接优雅降级、token 注入、init/shutdown 无崩溃 |
| `tests/test_rag_mcp.py`(本阶段新增, 5 个) | 无工具纯 RAG、工具调用流、工具失败降级、Supervisor github 路由、图级 E2E |
| `tests/test_mcp.py`(17 个) | 加密/Schema/配置解析/工具转换/DB 加密/调用缓存/真实 FastMCP stdio E2E |

全量: `cd backend && python -m pytest tests/ -v` — **63 passed**。

## 验证(对照验收 3 项)

1. **能列出可用 GitHub 工具**: 配好 `.env` 后启动, `init_github_mcp()` 返回 `McpToolInfo` 列表, `get_github_mcp_tools()` 非空。
2. **真实消息**: 发送「查一下 langchain-ai/langchain 最近的 5 个 issue」→ supervisor 命中 `github` 关键词 → RAG → 触发 `mcp_github_search_issues` 工具(需模型支持 tool calling)。
3. **断开不崩溃**: 未启用 / 连接失败 → `get_github_mcp_tools()` 返回 `[]`, RAG 保持纯问答。
