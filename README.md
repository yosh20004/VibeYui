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

- ### HeartbeatMonitor
  - 维持心率: 心率越高，llm越有可能产生一次调用
  - 当llm发出一次调用，进入紧张阶段，此时若外部与其反馈，则检测是否和其相关，若相关则做出回应维持；否则快速进入心率为0阶段
  - 心率为0时，持续监听外部输入，并缓慢增长，被唤醒几率逐渐增加
  - 在任何情况下被at / 在紧张状态时检测到用户与之互动则进入紧张状态

- ### Config
  - 负责统一管理依赖相关配置，并构建默认依赖实例
  - 模块路径: `src/config/`
  - 配置模板: `config/dependencies.example.json`（可提交）
  - 本地依赖配置: `config/dependencies.local.json`（已加入 `.gitignore`，不提交）
  - 读取顺序: 优先本地配置文件，其次环境变量（`LLM_*` / `MCP_*`）

- ### Adapter
  - 基于NoneBot接受外部事件和群聊消息
  - 获取群聊消息，并与核心组件交互做出回复
