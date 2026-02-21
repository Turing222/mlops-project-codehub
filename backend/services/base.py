from typing import Generic, TypeVar

UowT = TypeVar("UowT")


class BaseService(Generic[UowT]):  # noqa: UP046
    def __init__(self, uow: UowT):
        self.uow = uow
