# SQLAlchemy Async 常见陷阱

本文档记录在 SQLAlchemy + asyncpg 环境下反复踩过的坑，供后续开发参考。每条包含现象、根因和推荐写法。

## 1. MissingGreenlet：session 关闭后访问 ORM 属性

### 现象

```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called;
can't call await_only() here. Was IO attempted in an unexpected place?
```

典型触发位置：在 `async with uow:` 块**外面**读取 ORM 对象的属性。

### 根因

ORM 对象（如 `CreditAccount`）的属性访问由 SQLAlchemy 管理。当属性被标记为"过期"时（commit / savepoint 结束后可能发生），访问该属性会触发一次隐式 SQL 查询（lazy load）。这需要活跃的 async session，但此时 session 已被 `UnitOfWork.__aexit__` 关闭，asyncpg 无法在非 greenlet 上下文中执行 IO，于是抛出 MissingGreenlet。

时序：

1. `async with uow:` → session 创建
2. 业务代码拿到 ORM 对象（`account`, `tx`）
3. 离开 `async with` → `commit()` → `session.close()` → session 置 None
4. 块外访问 `account.balance` → SQLAlchemy 尝试 lazy load → 无可用 session → 💥

### 推荐写法

把所有 ORM 属性读取移到 session 存活期间，构造好纯 Python 值后再出块：

```python
async with credit_service.write() as uow:
    account, tx = await credit_service.daily_checkin(user_id)
    # ✅ session 还活着，属性读取安全
    result = CheckinResponse(
        balance=account.balance,
        amount_earned=tx.amount,
        expires_at=tx.expires_at,
    )
    await uow.commit()
return result  # result 是 Pydantic 对象，不依赖 session
```

反模式：

```python
async with credit_service.write():
    account, tx = await credit_service.daily_checkin(user_id)
# ❌ session 已关闭，account.balance 触发 lazy load → MissingGreenlet
return CheckinResponse(balance=account.balance, ...)
```

## 2. savepoint 导致属性过期

### 现象

即使在 `expire_on_commit=False` 的 session 中，经过 savepoint（`begin_nested`）后，部分 ORM 属性仍被标记为过期，后续访问触发 lazy load。

### 根因

`begin_nested()` 创建 SAVEPOINT，结束时 SQLAlchemy 可能将对象的特定属性标记为需要刷新。`expire_on_commit=False` 只控制外层 commit 的行为，不覆盖 savepoint 的属性失效逻辑。

### 推荐写法

对 savepoint 内创建/修改的对象，用 bulk UPDATE + 手动赋值代替 ORM 属性累加，避免触发过期刷新：

```python
# ✅ 不依赖 ORM 属性同步
new_balance = account.balance + amount
await credit_repo.update_account_balance(account.id, new_balance)
account.balance = new_balance  # 手动赋值，不触发 lazy load
```

反模式：

```python
# ❌ savepoint 后 account.balance 可能过期，+= 触发 lazy load
account.balance += amount
await credit_repo.update_account_balance(account.id, account.balance)
```

## 3. refresh 缺少 attribute_names 导致全量加载

### 现象

`session.refresh(obj)` 在 async 环境下可能对尚未完全初始化的对象触发不必要的全量属性加载。

### 推荐写法

只刷新你需要的属性：

```python
await session.refresh(account, attribute_names=["balance"])
```

反模式：

```python
await session.refresh(account)  # 全量加载，可能触发关联 relationship 的 IO
```

## 4. 组件测试 FakeUnitOfWork 缺少新增 repo

### 现象

新增了 `credit_repo` 到 `AbstractUnitOfWork` 和 `SQLAlchemyUnitOfWork`，但测试中的 `FakeUnitOfWork` 忘了同步，运行时报 `AttributeError: 'FakeUnitOfWork' object has no attribute 'credit_repo'`。

### 推荐写法

每次在 `AbstractUnitOfWork` 上新增 repo 属性时，同步更新所有 FakeUnitOfWork。对不需要复杂行为的 repo，用最小 stub：

```python
class FakeCreditRepo:
    async def get_account(self, user_id):
        from backend.models.orm.credits import CreditAccount
        return CreditAccount(user_id=user_id, balance=100)

    async def get_account_with_lock(self, user_id):
        return await self.get_account(user_id)

    # ... 其他方法返回 None / True / []
```

## 5. 检查清单

遇到 SQLAlchemy async 问题时，依次检查：

- [ ] ORM 属性是否在 session 存活期间读取？
- [ ] 是否经过 savepoint 后访问了可能过期的属性？
- [ ] `refresh` 是否限制了 `attribute_names`？
- [ ] FakeUnitOfWork 是否同步了新增的 repo？
- [ ] 是否有代码在 `async with uow:` 块外使用 ORM 对象？
