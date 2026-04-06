import random
import string

import urllib3
from locust import HttpUser, between, task

# 禁用 requests 库因为关闭 SSL 校验而可能抛出的安全警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class AiTutorUser(HttpUser):
    # 每个虚拟用户在执行任务之间等待 1 到 5 秒
    wait_time = between(1, 5)

    def on_start(self):
        """每个虚拟用户启动时调用的初始化逻辑"""
        # 全局关闭此虚拟用户的 SSL 证书校验（针对内网自签证书）
        self.client.verify = False

        self.session_id = None  # 初始化会话为 None，让后端自己创建
        # 生成随机用户名以支持并发压测，避免用户名冲突
        random_suffix = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=6)
        )
        self.username = f"locust_user_{random_suffix}"
        self.password = "locust_pass_123"

        # 1. 自动注册
        self.client.post(
            "/v1/auth/register",
            json={
                "username": self.username,
                "password": self.password,
                "confirm_password": self.password,
                "email": f"{self.username}@test.com",
            },
            name="/v1/auth/register",
        )

        # 2. 自动登录获取 Token
        resp = self.client.post(
            "/v1/auth/login",
            data={"username": self.username, "password": self.password},
            name="/v1/auth/login",
        )

        if resp.status_code == 200:
            token = resp.json().get("access_token")
            self.client.headers.update({"Authorization": f"Bearer {token}"})

    @task(3)
    def chat_workflow(self):
        """模拟核心聊天流，权重为 3"""
        payload = {
            "query": "你好，目前系统支持哪些机器学习工作流？",
            "session_id": self.session_id,
        }

        # 发送到真实的 chat 路由（使用 query_sent 避免 Locust 难以验证 SSE 流式结果）
        with self.client.post(
            "/v1/chat/query_sent",
            json={
                k: v for k, v in payload.items() if v is not None
            },  # 如果 session_id 为 None 则不传
            name="/v1/chat/query_sent",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                # 获取返回的 session_id，保存下来供该用户的下发查询使用
                response_data = response.json()
                if not self.session_id and "session_id" in response_data:
                    self.session_id = response_data["session_id"]
                response.success()
            else:
                response.failure(
                    f"Chat failed with status code: {response.status_code}"
                )

    @task(1)
    def health_check(self):
        """低频率检查系统存活，权重为 1"""
        self.client.get("/v1/health_check/live", name="Health Check")

    @task(2)
    def get_root(self):
        """模拟访问 API 根路径，权重为 2"""
        self.client.get("/", name="Root Index")
