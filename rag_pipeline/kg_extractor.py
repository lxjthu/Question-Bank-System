"""知识图谱提取：调用 DeepSeek API，将章节文本转为结构化知识图谱。"""
import json
import time

from openai import OpenAI

from . import db
from .config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from .prompts import kg_extraction_prompt


def _call_api(client: OpenAI, prompt: str, max_retries: int = 3, temperature: float = 0.3) -> str:
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=2000,
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


def _parse_json(raw: str) -> dict:
    """解析 API 返回的 JSON，容忍常见的 markdown 包裹问题。"""
    text = raw.strip()
    # 去掉 ```json ... ``` 或 ``` ... ```
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:] if lines[0].startswith("```") else lines)
    if text.endswith("```"):
        text = "\n".join(text.splitlines()[:-1])
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc}\n原始内容（前 300 字）:\n{raw[:300]}") from exc


def extract_kg_for_chapter(
    chapter: dict,
    client: OpenAI | None = None,
    subject_hint: str = '农业经济学',
) -> dict:
    """提取单章知识图谱，若 JSON 格式错误则自动重试一次。"""
    if client is None:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    prompt = kg_extraction_prompt(
        chapter["number"], chapter["name"], chapter["content"],
        subject_hint=subject_hint,
    )
    print(f"  -> 调用 DeepSeek 提取知识图谱...")
    raw = _call_api(client, prompt, temperature=0.3)

    try:
        return _parse_json(raw)
    except ValueError as exc:
        print(f"  [!] JSON 解析失败，追加指令重试：{exc}")
        retry_prompt = prompt + "\n\n请重新输出，只输出纯 JSON，不要有任何额外文字或代码块标记。"
        raw2 = _call_api(client, retry_prompt, temperature=0.1)
        return _parse_json(raw2)


def run_kg_extraction(chapters: list[dict], progress: dict, save_progress_fn) -> None:
    """批量提取知识图谱，支持断点续传。"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "sk-your-key-here":
        print("\n[ERROR] 未设置 DEEPSEEK_API_KEY，请先填写 .env 文件\n")
        return

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    done_ids: set[int] = set(progress.get("kg_extracted", []))
    pending = [ch for ch in chapters if ch["id"] not in done_ids]

    if not pending:
        print("\n[OK] 所有章节的知识图谱均已提取完成。\n")
        return

    print(f"\n待提取: {len(pending)} 章（已完成: {len(done_ids)}）\n")

    for idx, chapter in enumerate(pending):
        print(f"[{idx + 1}/{len(pending)}] {chapter['number']} {chapter['name']}")
        try:
            kg_data = extract_kg_for_chapter(chapter, client)

            # 持久化到 SQLite
            db.save_chapter(
                chapter["id"],
                chapter["number"],
                chapter["name"],
                chapter["content"],
                chapter["learning_goals"],
            )
            db.save_kg(chapter["id"], kg_data)

            # 更新断点进度
            done_ids.add(chapter["id"])
            progress["kg_extracted"] = sorted(done_ids)
            save_progress_fn()

            n_c = len(kg_data.get("concepts", []))
            n_r = len(kg_data.get("relations", []))
            n_k = len(kg_data.get("key_points", []))
            n_d = len(kg_data.get("difficulty_points", []))
            print(f"  [OK] {n_c} 个概念 | {n_r} 条关系 | {n_k} 个重点 | {n_d} 个难点")

            if idx < len(pending) - 1:
                time.sleep(1)  # 避免触发限速

        except Exception as exc:
            print(f"  [FAIL] 提取失败，已跳过，下次继续: {exc}\n")
