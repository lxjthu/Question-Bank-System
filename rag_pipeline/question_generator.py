"""题目生成：调用 DeepSeek API，基于章节文本 + 知识图谱生成题库。"""
import re
import time
from pathlib import Path

from openai import OpenAI

from . import db
from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    OUTPUT_DIR,
    QUESTION_CONFIG,
)
from .prompts import question_generation_prompt


def _call_api(client: OpenAI, prompt: str, max_retries: int = 3, temperature: float = 0.7) -> str:
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=6000,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            wait = 2 ** attempt
            print(f"  API 调用失败（第 {attempt + 1} 次）: {exc}")
            if attempt < max_retries - 1:
                print(f"  等待 {wait}s 后重试...")
                time.sleep(wait)
            else:
                raise


def _count_questions(text: str) -> dict[str, int]:
    """统计各题型数量，用于输出质量核查。"""
    return {
        "单选": len(re.findall(r"^\[单选\]", text, re.MULTILINE)),
        "多选": len(re.findall(r"^\[多选\]", text, re.MULTILINE)),
        "是非": len(re.findall(r"^\[是非\]", text, re.MULTILINE)),
        "简答": len(re.findall(r"^\[简答\]", text, re.MULTILINE)),
        "论述": len(re.findall(r"^\[简答>论述\]", text, re.MULTILINE)),
        "材料分析": len(re.findall(r"^\[简答>材料分析\]", text, re.MULTILINE)),
    }


def generate_for_chapter(chapter: dict, client: OpenAI | None = None) -> str:
    """为单章生成题目，返回符合导入格式的文本。"""
    if client is None:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    kg_data = db.get_chapter_kg(chapter["id"])
    prompt = question_generation_prompt(
        chapter["number"],
        chapter["name"],
        chapter["content"],
        kg_data,
        QUESTION_CONFIG,
    )

    print(f"  -> 调用 DeepSeek 生成题目...")
    raw = _call_api(client, prompt, temperature=0.7)

    counts = _count_questions(raw)
    total = sum(counts.values())
    counts_str = " | ".join(f"{k}:{v}" for k, v in counts.items() if v)
    print(f"  [OK] 共 {total} 题  [{counts_str}]")

    if total < 10:
        print(f"  [!] 题目数量偏少（{total}），建议检查输出文件")

    return raw


def save_questions(chapter: dict, content: str) -> Path:
    """将题目内容保存为 .txt 文件。"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", chapter["name"])[:20]
    filename = f"chapter_{chapter['id']:02d}_{chapter['number']}_{safe_name}.txt"
    filepath = OUTPUT_DIR / filename
    header = f"# {chapter['number']} {chapter['name']}\n# 知识图谱驱动出题 | 可直接导入题库系统\n\n"
    filepath.write_text(header + content, encoding="utf-8")
    return filepath


def merge_all_questions() -> Path | None:
    """合并所有章节题目文件为一个 all_questions.txt。"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    files = sorted(OUTPUT_DIR.glob("chapter_*.txt"))
    if not files:
        print("\n[!] output/ 目录下没有题目文件，请先生成题目。\n")
        return None

    merged = OUTPUT_DIR / "all_questions.txt"
    parts = [f.read_text(encoding="utf-8") for f in files]
    merged.write_text("\n\n".join(parts), encoding="utf-8")
    print(f"\n[OK] 已合并 {len(files)} 个章节文件 -> {merged}")
    return merged


def run_question_generation(
    chapters: list[dict],
    progress: dict,
    save_progress_fn,
    chapter_ids: list[int] | None = None,
) -> None:
    """批量生成题目，支持断点续传和指定章节。"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "sk-your-key-here":
        print("\n[ERROR] 未设置 DEEPSEEK_API_KEY，请先填写 .env 文件\n")
        return

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    kg_done: set[int] = set(progress.get("kg_extracted", []))
    q_done: set[int] = set(progress.get("questions_generated", []))

    # 确定目标章节
    target = chapters if chapter_ids is None else [ch for ch in chapters if ch["id"] in chapter_ids]
    pending = [ch for ch in target if ch["id"] not in q_done]

    # 过滤掉未提取 KG 的章节
    no_kg = [ch for ch in pending if ch["id"] not in kg_done]
    if no_kg:
        names = ", ".join(ch["number"] for ch in no_kg)
        print(f"\n[!] 以下章节尚未提取知识图谱，已跳过: {names}")
        pending = [ch for ch in pending if ch["id"] in kg_done]

    if not pending:
        print("\n[OK] 没有待生成题目的章节（或所选章节均已完成）。\n")
        return

    print(f"\n待生成: {len(pending)} 章（已完成: {len(q_done)}）\n")

    for idx, chapter in enumerate(pending):
        print(f"[{idx + 1}/{len(pending)}] {chapter['number']} {chapter['name']}")
        try:
            content = generate_for_chapter(chapter, client)
            filepath = save_questions(chapter, content)
            print(f"  -> 保存: {filepath.name}")

            q_done.add(chapter["id"])
            progress["questions_generated"] = sorted(q_done)
            save_progress_fn()

            if idx < len(pending) - 1:
                time.sleep(1)

        except Exception as exc:
            print(f"  [FAIL] 生成失败，已跳过，下次继续: {exc}\n")
