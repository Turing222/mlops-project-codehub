class AppError(Exception):
    """所有业务异常的基类"""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class ServiceError(AppError):
    """服务层发生的逻辑错误"""
    pass

class ValidationError(AppError):
    """数据校验失败"""
    pass