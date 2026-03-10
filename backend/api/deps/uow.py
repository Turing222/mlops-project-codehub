from fastapi import Request

from backend.services.unit_of_work import SQLAlchemyUnitOfWork


async def get_uow(request: Request) -> SQLAlchemyUnitOfWork:
    return SQLAlchemyUnitOfWork(request.app.state.session_factory)

