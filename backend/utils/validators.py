from typing import Annotated, Any

from pydantic import BeforeValidator


def tidy_string(v: Any) -> Any:
    """通用的去空格逻辑"""
    if isinstance(v, str):
        return v.strip()
    return v


def to_lower(v: Any) -> Any:
    """强制小写"""
    if isinstance(v, str):
        return v.lower()
    return v


# 组合成新的类型别名
TidyStr = Annotated[str, BeforeValidator(tidy_string)]
NormalizedEmail = Annotated[
    str, BeforeValidator(tidy_string), BeforeValidator(to_lower)
]
