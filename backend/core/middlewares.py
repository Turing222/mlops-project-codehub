import time

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse


# Request ID 注入、全局鉴权中间件放在这里
async def auth_and_timer_middleware(request: Request, call_next):
    # 1. 计时开始
    start_time = time.time()

    # 2. 简单的鉴权逻辑 (示例)
    # 排除掉不需要鉴权的接口，如登录、健康检查
    if request.url.path not in ["/login", "/docs", "/redoc", "/openapi.json"]:
        token = request.headers.get("Authorization")
        if not token:
            return JSONResponse(status_code=401, content={"detail": "未授权的访问"})

    # 3. 执行后续逻辑
    response = await call_next(request)

    # 4. 计时结束并记录到响应头
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)

    return response
