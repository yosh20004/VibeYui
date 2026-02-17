## VibeYui
- 一个基于llm的qq bot

## 核心组件
- ### Router
  - 负责接收用户at和一般输入，并进行处理

- ### LLM
  - 负责处理输入，并返回api服务结果
  
- ### Context Engine
  - 负责处理记忆
  - 若usr_msg是向ai发起的，则立刻处理
  - 若不是，则记录
  - 已接入Router：普通消息只记录，@消息立即调用LLM并携带近期记忆
