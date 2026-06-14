# Frontend Docs

这个目录是前端工程约定的入口，覆盖 `frontend/apps/admin` 的架构、迁移路线和开发标准。

## 必读文档

- [Architecture](architecture.md): 前端目标架构、技术栈、目录职责和核心边界。
- [Migration Plan](migration-plan.md): 从当前实现迁到目标架构的阶段计划。

## Standards

- [API](standards/api.md): API 封装、schema、错误、trace 和幂等约定。
- [State](standards/state.md): 本地状态、服务端状态和认证状态的分层规则。
- [Streaming](standards/streaming.md): 聊天 SSE / chunk 流式请求的实现边界。
- [Components](standards/components.md): 页面、feature、组件和表单的拆分约定。
- [Testing](standards/testing.md): 前端测试分层、覆盖重点和验收命令。
- [Styling](standards/styling.md): 样式组织、设计系统和响应式约定。

## 使用原则

- 先查 `architecture.md` 判断边界，再查对应 `standards/*` 做实现。
- 新增功能优先遵守标准；标准没有覆盖时，在对应文档里先留 `TODO` 或补充草案。
- 迁移过程保持小步可验证，不为了统一一次性重写所有页面。
