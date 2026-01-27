import logging
import os
import uuid

import chainlit as cl
import httpx

# 1. 从环境变量读取配置，默认值适配本地开发
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

API_VERSION = os.getenv("API_VERSION", "v1")
API_PREFIX = os.getenv("API_PREFIX", "proxy")

LOGIN_PATH = "login"

# 设置超时时间（AI 响应通常较慢，默认 5秒可能不够）
HTTP_TIMEOUT = 60.0

logger = logging.getLogger("chainlit")


@cl.on_chat_start
async def start():
    """
    应用启动逻辑
    """
    # 真实场景建议使用 Chainlit 的 Authentication 机制
    # 这里为了演示，增加 try-except 保护
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 假设你的登录接口需要用户名密码，或者 API Key
            resp = await client.post(
                f"{BACKEND_URL}/login", json={"username": "demo", "password": "123"}
            )
            resp.raise_for_status()  # 如果状态码不是 2xx，抛出异常

            token = resp.json().get("access_token")
            cl.user_session.set("auth_token", token)

            await cl.Message(content="✅ 系统连接成功，随时待命！").send()

    except Exception as e:
        logger.error(f"Login failed: {e}")
        await cl.Message(content=f"❌ 无法连接到后端服务: {str(e)}").send()


@cl.on_message
async def main(message: cl.Message):
    """
    消息处理主逻辑
    """
    token = cl.user_session.get("auth_token")
    if not token:
        await cl.Message(content="⚠️ 未登录，请刷新页面重试。").send()
        return

    # 生成本次请求的唯一 ID
    request_id = str(uuid.uuid4())

    # 定义 Step，给用户反馈
    step = cl.Step(name="思考中", type="run")  # type="run" 会显示旋转图标
    await step.send()

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.post(
                f"{BACKEND_URL}/ai-query",
                json={"content": message.content},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": request_id,
                },
            )
            response.raise_for_status()  # 关键：检查 4xx/5xx 错误

            data = response.json()

            # 更新 Step 的信息
            step.name = "处理完成"
            # 可以在这里展示 SQL 语句或耗时
            if "sql_latency" in data:
                step.output = f"SQL Latency: {data['sql_latency']}"
            await step.update()

            # 发送回复
            total_time = response.headers.get("X-Process-Time", "N/A")
            latency_text = f"{float(total_time):.2f}s" if total_time != "N/A" else "N/A"

            await cl.Message(
                content=f"{data['answer']}\n\n_⏱️ 耗时: {latency_text}_"
            ).send()

    except httpx.HTTPStatusError as e:
        # 处理 HTTP 错误 (404, 500, 401)
        step.name = "调用失败"
        step.status = cl.StepStatus.FAILED
        await step.update()

        error_msg = f"API Error ({e.response.status_code}): {e.response.text}"
        await cl.Message(content=f"❌ 服务端报错: {error_msg}").send()

    except httpx.RequestError as e:
        # 处理网络连接错误 (超时, 连接拒绝)
        step.name = "网络故障"
        step.status = cl.StepStatus.FAILED
        await step.update()

        await cl.Message(content=f"❌ 网络连接失败: 请检查后端服务是否启动。").send()

    except Exception as e:
        # 其他未知错误
        logger.exception("Unknown error")
        await cl.Message(content=f"❌ 发生未知错误: {str(e)}").send()
