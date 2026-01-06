from typing import Annotated
from fastapi import Query

# 把 T 和 Metadata 结合成一个新类型
SkipParam = Annotated[int, Query(ge=0, description="跳过前 N 条记录")]
LimitParam = Annotated[int, Query(ge=1, le=100, description="每页最大记录数")]
UsernameQuery = Annotated[
    str | None, 
    Query(min_length=0, max_length=20, description="要搜索的用户名")
]