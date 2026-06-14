"""Workflow and dispatcher import boundary tests — enforce web/worker dependency split.

职责：验证 application 和 infra 层的公开导入可达，以及 web 侧模块不直接依赖
worker tasks 或 AI runtime；边界：仅做 AST 解析和 importlib 导入，无运行时副作用。
"""

import ast
import importlib
import sys
from pathlib import Path


def test_chat_workflow_imports_from_application() -> None:
    from backend.application.chat.web_nonstream_workflow import ChatNonStreamWorkflow
    from backend.application.chat.web_stream_workflow import ChatWorkflow

    assert ChatWorkflow is not None
    assert ChatNonStreamWorkflow is not None


def test_knowledge_workflow_imports_from_application() -> None:
    from backend.application.knowledge.ingestion_workflow import (
        KnowledgeRAGWorkflow,
    )
    from backend.application.knowledge.upload_workflow import (
        KnowledgeUploadWorkflow,
    )

    assert KnowledgeRAGWorkflow is not None
    assert KnowledgeUploadWorkflow is not None


def test_dispatcher_imports_from_infra() -> None:
    from backend.infra.task_dispatcher import TaskDispatcher

    assert TaskDispatcher is not None


def test_worker_tasks_package_does_not_eager_import_task_modules() -> None:
    task_modules = [
        "backend.worker.tasks.credit_tasks",
        "backend.worker.tasks.knowledge_tasks",
        "backend.worker.tasks.llm_tasks",
    ]
    for module_name in ["backend.worker.tasks", *task_modules]:
        sys.modules.pop(module_name, None)

    module = importlib.import_module("backend.worker.tasks")

    assert module.__all__ == [
        "expire_credits_task",
        "generate_llm_stream_task",
        "ingest_knowledge_file_task",
    ]
    for module_name in task_modules:
        assert module_name not in sys.modules


def test_web_workflows_do_not_import_worker_or_ai_runtime() -> None:
    web_modules = [
        "backend.application.chat.web_stream_workflow",
        "backend.application.chat.web_nonstream_workflow",
        "backend.application.knowledge.upload_workflow",
        "backend.api.deps.workflows",
        "backend.api.dependencies",
    ]
    forbidden_prefixes = (
        "backend.worker.tasks",
        "backend.ai",
        "backend.api.deps.ai",
        "backend.application.chat.worker_generation_workflow",
        "backend.application.knowledge.ingestion_workflow",
    )

    for mod_name in web_modules:
        mod = importlib.import_module(mod_name)
        source = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(source):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    full = f"{module}.{alias.name}" if module else alias.name
                    assert not full.startswith(forbidden_prefixes), (
                        f"{mod_name} imports {full}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden_prefixes), (
                        f"{mod_name} imports {alias.name}"
                    )
