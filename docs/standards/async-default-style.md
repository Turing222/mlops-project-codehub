# 异步代码默认写法

本文档用于约定本项目中与 `async` 相关的默认编码风格，目标是降低心智负担，让 `def`、`async def`、`@staticmethod` 和 `asyncio.to_thread(...)` 的使用边界保持一致。

本文档偏“默认规则”，不是绝对规则。遇到明确的框架要求、第三方库约束或性能需求时，可以在局部做例外，但应先遵守默认写法。

## 1. 设计目标

我们希望异步代码满足以下要求：

- 函数签名尽量表达真实语义
- 不把同步逻辑伪装成异步逻辑
- 不在事件循环里直接执行明显阻塞的同步 I/O
- 默认写法简单、统一、好记

## 2. 默认规则

### 2.1 先默认写 `def`

如果一个函数本身不需要 `await`，默认写普通 `def`，不要为了“看起来统一”强行写成 `async def`。

推荐：

```python
def _sanitize_filename(filename: str) -> str:
    return filename.strip()
```

不推荐：

```python
async def _sanitize_filename(filename: str) -> str:
    return filename.strip()
```

原因：

- `async def` 不会让纯同步逻辑自动变快
- 调用方会被迫增加不必要的 `await`
- 容易让读代码的人误以为这里有异步 I/O

### 2.2 需要 `await` 时再写 `async def`

当函数内部需要等待异步操作时，才使用 `async def`，例如：

- `await upload_file.read(...)`
- `await repo.create(...)`
- `await client.get(...)`

示例：

```python
async def _read_upload_content(upload_file: UploadFile) -> bytes:
    return await upload_file.read()
```

### 2.3 不依赖 `self` 时，优先用 `@staticmethod`

如果一个方法：

- 不访问实例状态
- 不依赖 `self.uow`、`self.storage_root`、`self.max_upload_size_bytes` 之类的成员
- 只根据传入参数计算结果

则优先写成 `@staticmethod`。

示例：

```python
@staticmethod
def _cleanup_file(path: Path) -> None:
    path.unlink(missing_ok=True)
```

如果方法需要访问实例配置或依赖，则保持普通实例方法：

```python
def _build_storage_path(self, *, kb_id: uuid.UUID, filename: str) -> Path:
    ...
```

### 2.4 在异步代码中遇到同步阻塞 I/O，默认使用 `asyncio.to_thread(...)`

本项目默认约定：

- 在 `async def` 中，如果必须调用同步阻塞 I/O，优先使用 `await asyncio.to_thread(...)`

适用场景：

- 本地文件写入
- 文件移动/重命名
- 同步 SDK 调用
- 临时无法替换成原生 async API 的同步 I/O

示例：

```python
await asyncio.to_thread(self._move_file, temp_path, target_path)
await asyncio.to_thread(self._write_file, target_path, content)
```

## 3. 什么时候会阻塞事件循环

判断一个普通函数能不能直接在 `async def` 里调用，核心不是“它是不是普通函数”，而是“它会不会长时间占着事件循环不放”。

### 3.1 通常可以直接调用

这类函数通常很轻，不需要专门丢线程：

- 字符串处理
- 路径拼接
- 字典/列表组装
- 轻量参数校验
- 纯内存对象转换

示例：

```python
def _sanitize_filename(filename: str) -> str:
    ...
```

### 3.2 通常不要直接调用

这类同步逻辑通常会阻塞事件循环：

- `open/read/write`
- 文件移动、删除、扫描
- 同步网络请求
- 同步数据库客户端
- `time.sleep(...)`
- 明显耗时的解析、压缩、转换

对于这些场景：

- 有原生 async API 时，优先原生 async API
- 没有原生 async API 时，默认 `asyncio.to_thread(...)`

## 4. `asyncio.to_thread(...)` 的默认地位

本项目把 `asyncio.to_thread(...)` 作为“异步代码里包同步阻塞 I/O”的默认方案。

原因：

- 标准库自带，依赖最少
- 写法简洁
- 适合 service 层偶发的同步文件操作
- 对团队成员来说最容易记忆和统一

这意味着：

- 日常业务代码里，先不用纠结 `run_in_executor(...)`、`run_in_threadpool(...)` 或其他封装
- 先统一用 `to_thread(...)`
- 只有在确实需要更细线程池控制时，再引入其他方案

## 5. 什么时候不要默认用 `to_thread(...)`

### 5.1 有原生 async API 时

如果第三方库本身已经提供异步接口，优先直接使用异步接口，不要额外包线程池。

推荐：

```python
response = await async_client.get(url)
```

不推荐：

```python
response = await asyncio.to_thread(sync_client.get, url)
```

### 5.2 CPU 密集任务

`to_thread(...)` 主要适合阻塞 I/O，不是解决重 CPU 的首选。

对于以下场景：

- 大量文本解析
- PDF 结构提取
- 压缩/解压
- 大量 hash 计算
- 模型推理

优先考虑：

- 进程池
- TaskIQ 等后台任务队列

### 5.3 超长后台任务

如果一个操作本来就不应该在请求里完成，例如：

- 文档解析入库
- 向量化
- 大文件批处理

则应优先丢给后台任务系统，而不是在请求里用 `to_thread(...)` 硬顶。

## 6. 决策顺序

遇到一个新函数时，按下面顺序判断：

1. 它本身需要 `await` 吗？
   - 需要：`async def`
   - 不需要：先写 `def`

2. 它依赖 `self` 吗？
   - 不依赖：优先 `@staticmethod`
   - 依赖：普通实例方法

3. 它在 `async def` 中会做同步阻塞 I/O 吗？
   - 会：默认 `await asyncio.to_thread(...)`
   - 不会：直接调用

4. 它是重 CPU 或长后台任务吗？
   - 是：不要默认用 `to_thread(...)`
   - 改用进程池或任务队列

## 7. 推荐示例

### 7.1 轻量纯内存辅助函数

```python
@staticmethod
def _sanitize_filename(filename: str) -> str:
    return Path(filename).name.strip()
```

### 7.2 需要访问实例配置的同步函数

```python
def _build_storage_path(self, *, kb_id: uuid.UUID, filename: str) -> Path:
    kb_dir = self.storage_root / str(kb_id)
    kb_dir.mkdir(parents=True, exist_ok=True)
    return kb_dir / filename
```

### 7.3 在异步函数中包装同步阻塞 I/O

```python
async def save(self, path: Path, content: bytes) -> None:
    await asyncio.to_thread(self._write_file, path, content)
```

### 7.4 真正的异步函数

```python
async def _read_upload_content(self, upload_file: UploadFile) -> bytes:
    return await upload_file.read()
```

## 8. 一句话默认规范

本项目默认遵循以下约定：

- 没有 `await` 就不要写 `async def`
- 不依赖实例状态就优先用 `@staticmethod`
- 在异步代码中遇到同步阻塞 I/O，默认使用 `await asyncio.to_thread(...)`
- 重 CPU 或长任务不要硬塞进 `to_thread(...)`
