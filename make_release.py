"""make_release.py — 生成可一键运行的 release 压缩包。

运行方式：
    python make_release.py

输出：项目根目录下的 试题管理系统-release.zip
解压后双击 一键启动.bat 即可运行（需已安装 Python 3.8+）。
"""

import zipfile
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────

# release 包内的顶级目录名
RELEASE_DIR_NAME = "试题管理系统"

# 输出 zip 文件名（放在项目根目录）
OUTPUT_ZIP = "试题管理系统-release.zip"

# 需要打包的单个文件（相对于项目根目录）
INCLUDE_FILES = [
    # 核心应用
    "app/__init__.py",
    "app/db_models.py",
    "app/docx_importer.py",
    "app/factory.py",
    "app/models.py",
    "app/routes.py",
    "app/utils.py",
    "app/rag_routes.py",
    "app/kg_routes.py",
    "app/templates/index.html",
    "app/templates/kg.html",
    # 入口 & 配置
    "server.py",
    "config.py",
    "requirements.txt",
    "requirements-rag.txt",
    # Windows 一键启动
    "一键启动.bat",
    # 用户文档
    "README.md",
    "AI出题提示词.md",
]

# 需要递归打包的目录（相对于项目根目录）
# 格式：(目录路径, 排除的子路径集合)
INCLUDE_DIRS = [
    (
        "rag_pipeline",
        {
            "__pycache__",
            "output",          # 书籍专属生成题目，不随代码发布
            "bm25_index",      # 运行时生成的索引
            "qdrant_storage",  # 运行时生成的向量库
            "kg.db",           # 运行时生成的知识图谱
            "progress.json",   # 运行时进度文件
            "requirements.txt",      # 旧版依赖文件，已由根目录覆盖
            "requirements_rag.txt",  # 旧版依赖文件，已由根目录覆盖
            "技术文档.md",
            "真正RAG方案设计.md",
        },
    ),
    (
        "pptx_ocr",
        {
            "__pycache__",
            "requirements.txt",  # 已由根目录 requirements.txt 覆盖
        },
    ),
]

# ── 打包逻辑 ──────────────────────────────────────────────────────────────────

def add_dir(zf: zipfile.ZipFile, root: Path, dir_rel: str, excludes: set):
    """递归将目录下的文件加入 zip，跳过 excludes 中的名称。"""
    dir_path = root / dir_rel
    for src in sorted(dir_path.rglob("*")):
        if not src.is_file():
            continue
        # 检查路径中任意一段是否在排除列表
        parts = src.relative_to(dir_path).parts
        if any(p in excludes for p in parts):
            continue
        rel = src.relative_to(root).as_posix()
        arcname = f"{RELEASE_DIR_NAME}/{rel}"
        zf.write(src, arcname)
        print(f"  + {arcname}")


def main():
    root = Path(__file__).parent.resolve()
    output_path = root / OUTPUT_ZIP

    print(f"正在打包到 {output_path} ...")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        # 单文件
        missing = []
        for rel in INCLUDE_FILES:
            src = root / rel
            if not src.exists():
                missing.append(rel)
                continue
            arcname = f"{RELEASE_DIR_NAME}/{rel}"
            zf.write(src, arcname)
            print(f"  + {arcname}")

        if missing:
            print("\n[警告] 以下文件不存在，已跳过：")
            for m in missing:
                print(f"  - {m}")

        # 目录递归
        for dir_rel, excludes in INCLUDE_DIRS:
            if not (root / dir_rel).exists():
                print(f"\n[警告] 目录不存在，已跳过：{dir_rel}")
                continue
            print(f"\n  目录: {dir_rel}/")
            add_dir(zf, root, dir_rel, excludes)

    size_kb = output_path.stat().st_size / 1024
    print(f"\n完成！压缩包大小：{size_kb:.1f} KB")
    print(f"路径：{output_path}")
    print(f"\n使用说明：")
    print(f"  1. 解压 {OUTPUT_ZIP}")
    print(f"  2. 进入 {RELEASE_DIR_NAME}/ 目录")
    print(f"  3. 双击 一键启动.bat（需已安装 Python 3.8+）")


if __name__ == "__main__":
    main()
