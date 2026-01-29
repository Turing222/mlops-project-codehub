from typing import Generic, TypeVar

UowT = TypeVar("UowT")


class BaseService(Generic[UowT]):
    def __init__(self, uow: UowT):
        self.uow = uow
