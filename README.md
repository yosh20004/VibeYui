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
  - 提供文本规范化、结构化命令处理、Agent调用三个可独立替换接口

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
  - 默认会在 bot 启动时自动拉起 MCP server（默认命令: `python -m src.agent.mcp_servers.web_server`）
  - 最终回复也通过 MCP 工具 `emit_reply` 提交，模型可通过 `should_reply=false` 选择不回复
  - 子模块: `mcp_servers`
  - 子模块路径: `src/agent/mcp_servers/`
  - 用于放置可被 Agent 连接的 MCP server（例如 `web_server.py`）

- ### HeartbeatMonitor
  - 维持心率: 心率越高，llm越有可能产生一次调用
  - 当llm发出一次调用，进入紧张阶段，此时若外部与其反馈，则检测是否和其相关，若相关则做出回应维持；否则快速进入心率为0阶段
  - 心率为0时，持续监听外部输入，并缓慢增长，被唤醒几率逐渐增加
  - 在任何情况下被at / 在紧张状态时检测到用户与之互动则进入紧张状态
  - 被 @ 后 `is_tense` 将保持为 `true` 一段时间（默认 900 秒，可配置 `heartbeat.tense_hold_seconds`），期间不受心率值影响
  - 支持将心跳状态持久化到 SQLite（默认 `data/heartbeat.db`）

- ### Prompting
  - 模块路径: `src/prompting/`
  - 使用 `PromptManager` 统一管理系统提示词
  - Prompt 文案配置路径: `config/prompts.json`
  - 自动回复（心率触发）使用 `auto` prompt
  - 紧张回复（被 @ 或消息进入时已处于紧张态）使用 `tense` prompt（在 `auto` 基础上叠加紧张补充）

- ### Config
  - 负责统一管理依赖相关配置，并构建默认依赖实例
  - 模块路径: `src/config/`
  - 配置模板: `config/dependencies.example.json`（可提交）
  - 本地依赖配置: `data/dependencies.local.json`（已加入 `.gitignore`，不提交）
  - 兼容旧路径: 若 `data/dependencies.local.json` 不存在，会读取 `config/dependencies.local.json`
  - 读取顺序: 优先本地配置文件，其次环境变量（`LLM_*` / `MCP_*`）
  - 新增 QQ 群白名单配置 `qq.allowed_group_ids`，仅允许指定群号触发 LLM 处理

- ### Adapter
  - 基于NoneBot接受外部事件和群聊消息
  - 获取群聊消息，并与核心组件交互做出回复

- ### Workflow
  - 核心编排层已划分到 `src/core/workflow.py`
  - 只保留 `src/core` 单一入口，不再保留兼容别名层
  - 通过 `RouterPort / ContextPort / HeartbeatPort` 协议解耦实现
  - `MessageWorkflow` 显式流程为:
    `adapter -> router -> heartbeat -> context -> agent`
  - 内置 `LoggingHook` 打印工作日志，支持自定义 Hook 进行可插拔扩展

## 工作流接入示例
```python
from src.config import ConfigManager

config = ConfigManager()
workflow = config.build_message_workflow()

# 在 adapter 捕获消息后调用
reply = workflow.process("今天吃什么", at_user=False, source="qq_group")
if reply:
    print(reply)
```

若启用群白名单，请在调用时透传 `group_id`:
```python
reply = workflow.process(
    "今天吃什么",
    at_user=False,
    source="qq_group",
    group_id=123456789,
)
```

## 工作日志示例
```text
[workflow] adapter.captured | {'source': 'qq_group', 'message': '今天吃什么', 'at_user': False}
[workflow] heartbeat.checked | {'should_reply': True, 'heartbeat': 64.0, 'is_tense': True}
[workflow] context.composed | {'has_history': True}
[workflow] workflow.replied | {'reply': '...'}
```
