# Frontend Component Standard

## 目标

- 页面组件只做组合和路由级编排。
- 业务能力沉到 `features/*`。
- 表格、弹窗、表单、列表等可独立维护和测试。

## 推荐拆分

```text
src/
  pages/
    Admin/
      index.tsx
    Chat/
      index.tsx
  features/
    admin/
      users/
        UserSearchBar.tsx
        UserTable.tsx
        CreateUserModal.tsx
        EditUserModal.tsx
        use-admin-users.ts
    chat/
      use-chat-controller.ts
```

## 页面组件

页面组件可以负责：

- 路由级布局。
- 组合 feature 组件。
- 读取 route params / navigate。
- 处理少量页面级 UI 状态。

页面组件不应负责：

- 复杂 API 编排。
- 大段表格列定义和 mutation 逻辑混在一起。
- 流式协议解析。
- 多处复用的业务状态。

## 表单

- `Antd Form rules` 负责即时反馈。
- `Zod` 负责提交前 payload parse。
- 表单提交时先组装 payload，再交给 schema parse。

## TODO

- 明确 Admin 用户管理的拆分顺序。
- 补充 modal / table 组件命名模板。
- 补充 feature hook 的输入输出约定。
