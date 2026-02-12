"""
from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile, status

from backend.api.dependencies import get_ingestion_service
from backend.services.ingestion import IngestionService

router = APIRouter()


@router.post("/upload")
async def upload_file(
    file: UploadFile, service: IngestionService = Depends(get_ingestion_service)
):
    # 1. 先把文件存到 E 盘某个临时目录
    temp_path = f"E:/temp/{file.filename}"
    with open(temp_path, "wb") as f:
        f.write(await file.read())

    # 2. 调用处理逻辑
    # 注意：在生产环境建议用 TaskIQ 异步跑，现在先直接 await
    await service.process_file(temp_path, file_id=123)
    return {"status": "success"}
"""
