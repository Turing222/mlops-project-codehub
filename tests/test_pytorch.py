"""
import torch
from docling.document_converter import DocumentConverter
from sentence_transformers import SentenceTransformer


def check_env():
    print("--- 环境检查中 ---")
    # 1. 检查显卡
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"检测到设备: {device}")

    # 2. 尝试加载向量模型 (占显存)
    try:
        model = SentenceTransformer("BAAI/bge-base-zh-v1.5", device=device)
        print("✅ Sentence-Transformers: 载入成功")
    except Exception as e:
        print(f"❌ Sentence-Transformers: 载入失败 - {e}")

    # 3. 尝试初始化解析器 (占内存)
    try:
        converter = DocumentConverter()
        print("✅ Docling: 初始化成功")
    except Exception as e:
        print(f"❌ Docling: 初始化失败 - {e}")


if __name__ == "__main__":
    check_env()
"""
