"""
from docling.document_converter import DocumentConverter
from sentence_transformers import SentenceTransformer


class AIModelFactory:
    _embed_model = None
    _converter = None

    @classmethod
    def get_embed_model(cls):
        if cls._embed_model is None:
            # 加载 BGE 向量模型到显存 (约占 1-1.5G VRAM)
            cls._embed_model = SentenceTransformer(
                "BAAI/bge-base-zh-v1.5", device="cuda"
            )
        return cls._embed_model

    @classmethod
    def get_docling_converter(cls):
        if cls._converter is None:
            # 针对 16G RAM 优化的 Docling 配置
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import PdfFormatOption

            options = PdfPipelineOptions(do_ocr=False)  # 只要是文字版PDF，关闭OCR省内存
            options.device = "cuda"  # 尽量利用显卡推理

            cls._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=options)
                }
            )
        return cls._converter
"""
