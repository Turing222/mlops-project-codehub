"""Service base types.

职责：提供 service 层共享的 UnitOfWork 持有约定。
边界：本模块不实现事务逻辑；事务生命周期由具体 UnitOfWork 管理。
"""

from typing import Generic, TypeVar

UowT = TypeVar("UowT")


class BaseService(Generic[UowT]):  # noqa: UP046
    """持有 UnitOfWork 的 service 基类。"""

    def __init__(self, uow: UowT) -> None:
        self.uow = uow
