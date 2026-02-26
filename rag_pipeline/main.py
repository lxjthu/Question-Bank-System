#!/usr/bin/env python3
"""
农业经济学 AI 题库生成系统
基于 DeepSeek API + 知识图谱驱动

用法：
    python -m rag_pipeline.main
    或
    python -m rag_pipeline          (需要 rag_pipeline/__main__.py)
"""
import json
import sys
from pathlib import Path

from .config import DB_PATH, DEEPSEEK_API_KEY, PROGRESS_FILE
from . import db
from .parser import parse_md, preview_chapters
from .kg_extractor import run_kg_extraction
from .question_generator import run_question_generation, merge_all_questions


# -- 进度文件读写 -------------------------------------------------------------

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"kg_extracted": [], "questions_generated": []}


def save_progress(progress: dict) -> None:
    PROGRESS_FILE.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# -- UI 辅助 ------------------------------------------------------------------

BANNER = """
+----------------------------------------------+
|  农业经济学  AI 题库生成系统  v1.0          |
|  DeepSeek API + 概念关系图谱驱动            |
+----------------------------------------------+"""


def print_menu(progress: dict) -> None:
    kg_n = len(progress.get("kg_extracted", []))
    q_n = len(progress.get("questions_generated", []))
    print(f"\n 当前进度 >>  知识图谱已提取 {kg_n} 章 | 题目已生成 {q_n} 章\n")
    print(" [1] 解析文档          -> 预览所有章节")
    print(" [2] 提取知识图谱      -> 调用 DeepSeek，结果存入 kg.db（支持断点续传）")
    print(" [3] 查看知识图谱      -> 查看某章的概念与关系")
    print(" [4] 生成题目（全部）  -> 对所有已提取章节出题（支持断点续传）")
    print(" [5] 生成题目（选章）  -> 手动选择章节出题")
    print(" [6] 导出合并题库      -> 合并所有 chapter_*.txt -> all_questions.txt")
    print(" [7] 重置断点进度      -> 清除 progress.json（已生成文件和 DB 保留）")
    print(" [0] 退出\n")


def check_api_key() -> bool:
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "sk-your-key-here":
        print("\n[ERROR] 请先在项目根目录的 .env 文件中填写 DEEPSEEK_API_KEY")
        print("   示例：DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx\n")
        return False
    return True


# -- 菜单动作 -----------------------------------------------------------------

def action_view_kg(chapters: list[dict]) -> None:
    if not DB_PATH.exists():
        print("\n[!] 知识图谱数据库不存在，请先执行「提取知识图谱」\n")
        return

    all_ch = db.get_all_chapters()
    if not all_ch:
        print("\n[!] 知识图谱为空，请先执行「提取知识图谱」\n")
        return

    print("\n可查看的章节：")
    for ch in all_ch:
        print(f"  [{ch['id']:2d}] {ch['number']} {ch['name']}")

    try:
        ch_id = int(input("\n请输入章节编号: ").strip())
    except ValueError:
        print("无效输入")
        return

    kg = db.get_chapter_kg(ch_id)
    concepts = kg["concepts"]
    relations = kg["relations"]

    key_pts = [c["name"] for c in concepts if c.get("is_key_point")]
    diff_pts = [c["name"] for c in concepts if c.get("is_difficult_point")]

    REL = {
        "is_a": "是一种",
        "contrasts_with": "对比于",
        "depends_on": "依赖",
        "leads_to": "导致",
    }

    print(f"\n{'-' * 48}")
    print(f"重点知识点（{len(key_pts)}）: {', '.join(key_pts) or '无'}")
    print(f"难点知识点（{len(diff_pts)}）: {', '.join(diff_pts) or '无'}")
    print(f"\n全部概念（{len(concepts)}）:")
    for c in concepts:
        tags = []
        if c.get("is_key_point"):
            tags.append("重点")
        if c.get("is_difficult_point"):
            tags.append("难点")
        tag_str = f" [{'/'.join(tags)}]" if tags else ""
        desc = f" - {c['description']}" if c.get("description") else ""
        print(f"  * {c['name']}{tag_str}{desc}")

    if relations:
        print(f"\n关系（{len(relations)}）:")
        for r in relations:
            label = REL.get(r["type"], r["type"])
            print(f"  {r['from']}  --[{label}]-->  {r['to']}")
    print(f"{'-' * 48}\n")


def select_chapters(chapters: list[dict]) -> list[int]:
    """交互式多选章节，返回 chapter id 列表。"""
    print("\n可选章节：")
    for ch in chapters:
        print(f"  [{ch['id']:2d}] {ch['number']} {ch['name']}")
    print("\n输入章节编号（多个用英文逗号分隔，如 1,3,5），或输入 all 选择全部：")
    sel = input("选择章节：").strip()

    if sel.lower() == "all":
        return [ch["id"] for ch in chapters]
    try:
        ids = [int(x.strip()) for x in sel.split(",")]
        valid = {ch["id"] for ch in chapters}
        bad = [i for i in ids if i not in valid]
        if bad:
            print(f"[!] 无效章节编号（已忽略）: {bad}")
        return [i for i in ids if i in valid]
    except ValueError:
        print("输入格式错误")
        return []


# -- 主循环 -------------------------------------------------------------------

def main() -> None:
    print(BANNER)

    if not check_api_key():
        sys.exit(1)

    db.init_db()
    progress = load_progress()
    _chapters: list[dict] | None = None

    def _save():
        save_progress(progress)

    def ensure_chapters() -> list[dict]:
        nonlocal _chapters
        if _chapters is None:
            print("\n正在解析文档...")
            _chapters = parse_md()
            preview_chapters(_chapters)
        return _chapters

    while True:
        print_menu(progress)
        choice = input("请输入选项: ").strip()

        if choice == "0":
            print("\n再见！\n")
            break

        elif choice == "1":
            _chapters = parse_md()
            preview_chapters(_chapters)

        elif choice == "2":
            chapters = ensure_chapters()
            run_kg_extraction(chapters, progress, _save)

        elif choice == "3":
            chapters = ensure_chapters()
            action_view_kg(chapters)

        elif choice == "4":
            chapters = ensure_chapters()
            run_question_generation(chapters, progress, _save)

        elif choice == "5":
            chapters = ensure_chapters()
            ids = select_chapters(chapters)
            if ids:
                run_question_generation(chapters, progress, _save, chapter_ids=ids)

        elif choice == "6":
            merge_all_questions()

        elif choice == "7":
            confirm = input("\n确认重置断点进度？（y/n）: ").strip().lower()
            if confirm == "y":
                progress = {"kg_extracted": [], "questions_generated": []}
                _save()
                print("[OK] 进度已重置（已生成文件和 kg.db 保留）")

        else:
            print("无效选项，请重新输入")


if __name__ == "__main__":
    main()
