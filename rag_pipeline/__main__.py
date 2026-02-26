"""允许 python -m rag_pipeline 直接运行。"""
import sys

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 终端乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from .main import main

main()
