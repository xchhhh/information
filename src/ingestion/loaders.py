import os                          # 处理目录与路径
import shutil                      # 检查系统命令是否存在（如 antiword / libreoffice）
import subprocess                  # 调用系统命令把 .doc 转文本
import tempfile                    # 给 libreoffice 转出的临时文件一个落脚目录
import logging                     # 记录“扫描件空读”等告警，便于排查“内容缺少”
from langchain_community.document_loaders import TextLoader      # txt/md 加载器
from langchain_core.documents import Document                   # 统一文档结构，手写 PDF/doc 时用
from common.config import BASE_DIR                              # 项目根，保证路径不依赖“当前工作目录”

logger = logging.getLogger("ingestion.loaders")

# —— 尝试导入更强的 PDF 加载器 pdfplumber（纯 Python，pip 即可）——
# 它比 PyPDFLoader 更鲁棒：能处理加密明文 PDF、表格、残缺文件；优先用它，失败再回退
try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False
    from langchain_community.document_loaders import PyPDFLoader  # 回退方案

# —— 尝试导入 docx2txt（纯 Python，pip 即可），用于读取 .docx ——
try:
    import docx2txt
    _HAS_DOCX2TXT = True
except ImportError:
    _HAS_DOCX2TXT = False


def _load_pdf(path):
    """用 pdfplumber 逐页提取文本（比 PyPDFLoader 更鲁棒）。
    返回 list[Document]，每页一个；文本为空则打警告（不再是静默空读）。"""
    docs = []
    if _HAS_PDFPLUMBER:
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                txt = page.extract_text() or ""           # 提取该页正文
                # 顺带把表格内容也抽出来拼到文本后，避免表格信息丢失
                for table in (page.extract_tables() or []):
                    for row in table:
                        cells = [str(c) for c in row if c]   # 去掉空单元格
                        if cells:
                            txt += "\n" + " | ".join(cells)
                docs.append(Document(
                    page_content=txt,
                    metadata={"source": path, "page": i + 1},
                ))
        # 整篇都没抽到文字 → 极可能是扫描件（无文本层），明确告警（等 OCR 支持）
        if not any(d.page_content.strip() for d in docs):
            logger.warning(
                "[loaders] %s 未提取到文本，疑似扫描件/图片型 PDF（无文本层），"
                "需 OCR 才能识别，本次已跳过", path)
        return docs
    # 回退：PyPDFLoader（老方案）
    return PyPDFLoader(path).load()


def _load_docx(path):
    """用 docx2txt 读取 .docx（Word 2007+，纯 Python，无需系统包）。"""
    if not _HAS_DOCX2TXT:
        raise RuntimeError("处理 .docx 需先 pip install docx2txt")
    text = docx2txt.process(path) or ""
    return [Document(page_content=text, metadata={"source": path})]


def _load_doc(path):
    """读取老版 .doc（Word 97-2003）。纯 Python 无能为力，需系统装 antiword 或 libreoffice。"""
    # 方案1：antiword（轻量，yum install -y antiword）
    if shutil.which("antiword"):
        r = subprocess.run(["antiword", path], capture_output=True, text=True)
        if r.returncode == 0:
            return [Document(page_content=r.stdout, metadata={"source": path})]
    # 方案2：libreoffice（重但最通用，headless 转 txt）
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if soffice:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([soffice, "--headless", "--convert-to", "txt:Text",
                            "--outdir", td, path], capture_output=True, text=True)
            out = os.path.join(td, os.path.splitext(os.path.basename(path))[0] + ".txt")
            if os.path.exists(out):
                with open(out, encoding="utf-8", errors="ignore") as fh:
                    return [Document(page_content=fh.read(), metadata={"source": path})]
    # 都没装 → 抛清晰错误，提醒去装系统包（而不是静默跳过让内容丢失）
    raise RuntimeError(
        "处理 .doc 需服务器安装 antiword 或 libreoffice：\n"
        "  TencentOS/CentOS: yum install -y antiword\n"
        "  Ubuntu/Debian:    apt-get install -y antiword")


def _load_image(path):
    """图片（png/jpg）本次仅占位：OCR 尚未启用，友好跳过并打日志，避免静默空读。"""
    logger.warning(
        "[loaders] %s 为图片，当前未启用 OCR，已跳过"
        "（图片文字识别将在第二步加入）", path)
    return []


def load_documents(folder=None):
    # folder 不传时，默认读项目根下的 data/raw（你的原始资料放这里）
    folder = folder or os.path.join(BASE_DIR, "data", "raw")
    docs = []                                   # 用来装加载好的文档
    for root, _, files in os.walk(folder):      # 递归遍历该目录所有文件
        for fn in files:                        # 逐个文件名
            p = os.path.join(root, fn)          # 拼出完整路径
            low = fn.lower()
            if low.endswith((".txt", ".md")):           # 文本 / Markdown
                docs += TextLoader(p, encoding="utf-8").load()
            elif low.endswith(".pdf"):                  # PDF（鲁棒加载）
                docs += _load_pdf(p)
            elif low.endswith(".docx"):                 # Word 2007+
                docs += _load_docx(p)
            elif low.endswith(".doc"):                  # 老版 Word
                docs += _load_doc(p)
            elif low.endswith((".png", ".jpg", ".jpeg")):  # 图片（占位）
                docs += _load_image(p)
            # 其它未识别类型：静默跳过（不影响其它文件入库）
    return docs                                 # 返回所有文档
