"""make_release.py — 生成可一键运行的 release 压缩包。

运行方式：
    python make_release.py

输出：项目根目录下的 试题管理系统-release.zip
解压后双击 一键启动.bat 即可运行（需已安装 Python 3.8+）。
"""

import os
import zipfile
import shutil
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────

# release 包内的顶级目录名
RELEASE_DIR_NAME = "试题管理系统"

# 输出 zip 文件名（放在项目根目录）
OUTPUT_ZIP = "试题管理系统-release.zip"

# 需要打包的文件/目录（相对于项目根目录）
INCLUDE = [
    # 核心应用
    "app/__init__.py",
    "app/db_models.py",
    "app/docx_importer.py",
    "app/factory.py",
    "app/models.py",
    "app/routes.py",
    "app/utils.py",
    "app/templates/index.html",
    # 入口 & 配置
    "server.py",
    "config.py",
    "requirements.txt",
    # Windows 一键启动
    "一键启动.bat",
    # 用户文档
    "README.md",
    "AI出题提示词.md",
]

# ── 打包逻辑 ──────────────────────────────────────────────────────────────────

def main():
    root = Path(__file__).parent.resolve()
    output_path = root / OUTPUT_ZIP

    print(f"正在打包到 {output_path} ...")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        missing = []
        for rel in INCLUDE:
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

    size_kb = output_path.stat().st_size / 1024
    print(f"\n完成！压缩包大小：{size_kb:.1f} KB")
    print(f"路径：{output_path}")
    print(f"\n使用说明：")
    print(f"  1. 解压 {OUTPUT_ZIP}")
    print(f"  2. 进入 {RELEASE_DIR_NAME}/ 目录")
    print(f"  3. 双击 一键启动.bat（需已安装 Python 3.8+）")


if __name__ == "__main__":
    main()
