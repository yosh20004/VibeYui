## VibeYui
- 一个基于llm的qq bot

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
