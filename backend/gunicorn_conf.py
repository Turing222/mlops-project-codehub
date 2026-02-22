# gunicorn_conf.py
workers = 4  # 开启4个进程（通常为 CPU核心数 * 2 + 1）
worker_class = "uvicorn.workers.UvicornWorker"  # 重点：指定使用 Uvicorn 作为协议解析器
bind = "0.0.0.0:8000"  # 监听内部端口
