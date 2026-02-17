## VibeYui
- 一个基于llm的qq bot

## 安装依赖
1. 创建虚拟环境: `python3 -m venv .venv`
2. 激活虚拟环境: `source .venv/bin/activate`
3. 升级 pip: `python -m pip install --upgrade pip`
4. 安装依赖: `pip install -r requirements.txt`
5. 若在受限网络环境，请先配置 PyPI 镜像或代理后再安装

## 核心组件
- ### Router
  - 负责接收用户at和一般输入，并进行处理

- ### LLM
  - 负责处理输入，并返回api服务结果
  
- ### Context Engine
  - 只负责处理最近上下文（默认最近100条）
  - 若usr_msg是向ai发起的，则立刻处理
  - 若不是，则记录

- ### Memory Pool
  - 负责管理更远期记忆（长时记忆）
  - 写入时立即落盘（`data/memory_pool.jsonl`）防止丢失
  - Context Engine 启动时从 Memory Pool 回填最近上下文

- ### Agent
  - 负责 LLM 与工具调用编排（是否调用工具、调用后回注结果）
  - 通过官方 `mcp` Python SDK 与 MCP Server 通信
  - 子模块: `mcp_servers`
  - 子模块路径: `src/agent/mcp_servers/`
  - 用于放置可被 Agent 连接的 MCP server（例如 `web_server.py`）
