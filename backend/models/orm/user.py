from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.orm.base import AuditMixin, Base, BaseIdModel


class User(Base, BaseIdModel, AuditMixin):
    __tablename__ = "users"

    # 使用 Mapped 明确 Python 类型，mapped_column 明确数据库约束
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False, comment="B端登录唯一标识"
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )

    # Token 管理
    max_tokens: Mapped[int] = mapped_column(
        default=100000, server_default=text("100000"), comment="用户 Token 总额度"
    )
    used_tokens: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), comment="用户已消费 Token 数"
    )

    # 核心安全字段：绝不出现在 Schema 中
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # 将来可以在这里加 relationship
    # roles: List["Role"] = Relationship(...)
