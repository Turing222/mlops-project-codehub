# 后端接口风格标准

本文档约定后端接口边界的默认写法，重点统一四件事：变量命名、错误消息回复、类型标注、注释标准。

这里的“接口边界”包括 HTTP endpoint、依赖注入函数、middleware、异常处理器，以及 service / workflow / repository 暴露给其他模块调用的公共方法。

## 1. 变量命名

默认规则：

- Python 标识符统一使用英文。
- 变量和函数使用 `snake_case`。
- 类使用 `PascalCase`。
- 常量使用 `UPPER_SNAKE_CASE`。
- 布尔变量优先使用 `is_`、`has_`、`should_`、`can_` 前缀。

允许的常见缩写：

- `id`
- `db`
- `llm`
- `rag`
- `kb`
- `s3`
- `ip`
- `url`
- `api`
- `http`
- `jwt`
- `otel`

接口边界和本次触碰代码里应避免使用过泛的短名，例如：

- `res`：改为 `eval_result`、`response_payload` 等领域名。
- `ret`：改为实际返回内容名。
- `tmp`：改为 `temp_path`、`temp_file` 等。
- `obj`：改为具体模型名，例如 `knowledge_file`。
- `conn`：改为 `redis_connection`、`db_connection` 等。
- `rid`：改为 `request_id`。

## 2. 错误消息回复

HTTP 错误响应保持统一结构：

```json
{
  "error_code": "RESOURCE_NOT_FOUND",
  "message": "资源不存在",
  "details": {},
  "request_id": "..."
}
```

默认规则：

- `message` 是用户可见文案，统一使用中文。
- `message` 不暴露内部异常、实现细节、算法名或依赖服务细节。
- `error_code` 是程序判断依据，统一使用英文 `UPPER_SNAKE_CASE`。
- `details` 只放安全的结构化信息。
- `details` 的 key 使用 `snake_case`。
- UUID、Path 等对象放入 `details` 前先转成字符串。
- 没有额外信息时使用 `{}`。

示例：

```python
raise app_not_found(
    "用户不存在",
    code="USER_NOT_FOUND",
    details={"user_id": str(user_id)},
)
```

## 3. 类型标注

默认规则：

- HTTP endpoint 必须显式标注返回类型。
- dependency provider 必须显式标注返回类型。
- middleware、setup 函数和异常处理器必须显式标注返回类型。
- service / workflow / repository 的公共方法必须显式标注返回类型。
- `__init__` 必须显式标注 `-> None`。
- 私有 helper 不强制全量补齐，但触碰到时应顺手补齐。

不为了“全标注”引入复杂类型别名或大量无意义的 `Any`。当类型确实来自第三方动态对象时，可以保留局部 `Any`，但公共接口应尽量表达真实返回值。

## 4. 注释标准

默认规则：

- 核心模块应在文件头部使用模块 docstring 简要说明职责和边界。
- 适用范围包括 service、workflow、middleware、任务编排、核心配置和配置生成逻辑。
- 模块头部可以先写一句英文概括，再用中文说明职责、边界和重要副作用。
- 类 docstring 保持一句话职责说明；如果模块头部已经说明清楚，类上不重复长说明。
- 普通代码内部注释从简，只解释“为什么这样做”和“这里有什么风险”。
- 不写流水账式注释，例如“获取用户”“执行查询”“返回结果”。
- 只有算法步骤、状态机、迁移步骤、补偿逻辑等复杂流程，才保留编号注释。

推荐模块头部写法：

```python
"""Knowledge upload workflow.

职责：保存上传文件、创建异步任务，并投递知识库入库任务。
边界：本模块不解析文件内容；解析与向量化由 KnowledgeRAGWorkflow 处理。
失败处理：任务创建或投递失败时，负责回写文件/任务失败状态。
"""
```

推荐内部注释写法：

```python
# workspace 知识库必须重新校验成员权限，避免 owner 身份绕过降级后的权限。
```

不推荐：

```python
# 获取用户
user = await repo.get(user_id)
```

一句话标准：模块头部说明职责和边界，内部注释只写原因和风险；模块头部可英文一句加中文说明，普通注释使用中文并保留必要英文术语。
