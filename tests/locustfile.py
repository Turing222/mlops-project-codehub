import uuid
from locust import HttpUser, task, between

class AiTutorUser(HttpUser):
    # 每个虚拟用户在执行任务之间等待 1 到 5 秒
    wait_time = between(1, 5)

    def on_start(self):
        """每个虚拟用户启动时调用的初始化逻辑"""
        self.session_id = str(uuid.uuid4())
        # 如果系统需要登录，可以在这里执行登录逻辑并保存 Token
        # self.client.post("/auth/login", json={"username": "test", "password": "..."})

    @task(3)
    def chat_workflow(self):
        """模拟核心聊天流，权重为 3"""
        payload = {
            "session_id": self.session_id,
            "query_text": "你好，请解释一下什么是 MLOps？",
            "conversation_history": []
        }
        # 使用自定义的标识符来命名请求，方便在 Locust 仪表盘查看分类
        with self.client.post(
            "/v1/chat/completions", 
            json=payload, 
            name="/v1/chat/completions",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Chat failed with status code: {response.status_code}")

    @task(1)
    def health_check(self):
        """低频率检查系统存活，权重为 1"""
        self.client.get("/v1/health_check/live", name="Health Check")

    @task(2)
    def get_root(self):
        """模拟访问首页，权重为 2"""
        self.client.get("/", name="Root Index")
