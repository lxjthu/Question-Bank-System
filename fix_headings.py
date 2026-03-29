"""fix_headings.py — 标题层级修复 + 非内容段落清理 命令行工具

用法:
    python fix_headings.py <path/to/file.md> [--subject 科目名称] [--dry-run]

流程:
    1. 读取 .md 文件，清理 OCR 产物（页码标记等）
    2. 提取所有标题
    3. 调用 DeepSeek Layer 0 分析章节结构
    4. 先删除非内容段落（学习目标/小结/思考题等）
    5. 修复标题层级（章/节/大目/小目/细目 全6级）
    6. 写回文件（原文件备份为 .bak.md）

API Key 优先级：--api-key 参数 > .env DEEPSEEK_API_KEY > 环境变量
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

# ── 确保能 import app 包 ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from app.rag_routes import (
    _clean_headings_with_ai,
    _clean_ocr_md,
    _extract_all_headings,
    _apply_semantic_heading_remaps,
    _remove_non_content_sections,
)


# ── API Key 读取 ──────────────────────────────────────────────────────────────

def _load_api_key(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env_file = Path(__file__).parent / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('DEEPSEEK_API_KEY='):
                val = line.split('=', 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    return os.environ.get('DEEPSEEK_API_KEY', '')


# ── 统计工具 ──────────────────────────────────────────────────────────────────

def _level_dist(text: str) -> dict:
    return dict(Counter(h['level'] for h in _extract_all_headings(text)))


# ── 主流程 ────────────────────────────────────────────────────────────────────

def fix_headings(
    md_path: Path,
    subject: str = '',
    api_key: str = '',
    dry_run: bool = False,
) -> dict:
    """对单个 .md 文件执行完整标题修复流程，返回统计摘要。"""

    print(f"\n{'='*60}")
    print(f"文件: {md_path.name}")
    print('='*60)

    # Step 1: 读取 + OCR 清理
    raw = md_path.read_text(encoding='utf-8', errors='replace')
    cleaned, had_markers = _clean_ocr_md(raw)
    if had_markers:
        print(f"  [OCR清理] 检测到页码标记，已清除")

    orig_dist = _level_dist(cleaned)
    orig_headings = _extract_all_headings(cleaned)
    print(f"  [原始结构] {orig_dist}  共 {len(orig_headings)} 个标题")

    # Step 2: 调用 DeepSeek Layer 0
    if not api_key:
        print("  [警告] 未找到 DEEPSEEK_API_KEY，跳过 AI 分析，仅做 OCR 清理写回")
        if not dry_run:
            _writeback(md_path, cleaned)
        return {'file': md_path.name, 'skipped': 'no_api_key'}

    print(f"  [Layer 0] 正在调用 DeepSeek 分析标题结构...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com', timeout=180)
        hierarchy = _clean_headings_with_ai(orig_headings, subject, client)
    except Exception as e:
        print(f"  [错误] DeepSeek 调用失败: {e}")
        return {'file': md_path.name, 'error': str(e)}

    if hierarchy is None:
        print("  [降级] AI 分析返回 None，仅做 OCR 清理写回")
        if not dry_run:
            _writeback(md_path, cleaned)
        return {'file': md_path.name, 'skipped': 'ai_returned_none'}

    flat_detected = hierarchy.get('flat_detected', False)
    sm = hierarchy.get('semantic_map', {})
    nc = hierarchy.get('non_content_texts') or set()
    en = hierarchy.get('extraction_nodes', [])
    ct = hierarchy.get('chapters_tree', [])
    print(f"  flat_detected={flat_detected}, flat_level={hierarchy.get('flat_level')}")
    print(f"  semantic_map={sm}")
    print(f"  章={len(ct)} 个, extraction_nodes={len(en)} 个")
    print(f"  non_content_texts({len(nc)})={sorted(nc)}")

    # Step 3: 先删非内容段落
    text = cleaned
    if nc:
        text = _remove_non_content_sections(text, nc)
        removed_headings = [h['text'] for h in orig_headings if h['text'] in nc]
        print(f"  [去除非内容] 已删除: {removed_headings}")
    after_remove_dist = _level_dist(text)

    # Step 4: 修复标题层级（remap）
    if flat_detected and ct:
        text = _apply_semantic_heading_remaps(text, hierarchy)
    after_remap_dist = _level_dist(text)
    print(f"  [修复后结构] {after_remap_dist}")

    # extraction_nodes 可找到率
    found = sum(
        1 for n in en
        if re.search(r'^#{2,6}\s+' + re.escape(n), text, re.MULTILINE)
    )
    if en:
        print(f"  extraction_nodes 可找到: {found}/{len(en)}")

    # Step 5: 写回
    if not dry_run:
        _writeback(md_path, text)
    else:
        print(f"  [dry-run] 跳过写回")

    return {
        'file': md_path.name,
        'orig_dist': orig_dist,
        'after_remove_dist': after_remove_dist,
        'after_remap_dist': after_remap_dist,
        'non_content_removed': sorted(nc),
        'extraction_nodes': en,
        'extraction_nodes_found': found,
        'flat_detected': flat_detected,
    }


def _writeback(path: Path, text: str):
    bak = path.with_suffix('.bak.md')
    shutil.copy2(path, bak)
    path.write_text(text, encoding='utf-8')
    print(f"  [写回] 已备份 → {bak.name}")
    print(f"  [写回] 已写入 → {path.name}")


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='标题层级修复 + 非内容段落清理工具')
    parser.add_argument('files', nargs='+', help='.md 文件路径（支持多个）')
    parser.add_argument('--subject', default='', help='科目名称，传给 AI 提高准确率')
    parser.add_argument('--api-key', default='', dest='api_key', help='DeepSeek API Key（覆盖 .env）')
    parser.add_argument('--dry-run', action='store_true', help='仅分析，不写回文件')
    args = parser.parse_args()

    api_key = _load_api_key(args.api_key or None)

    results = []
    for fstr in args.files:
        path = Path(fstr)
        if not path.exists():
            print(f"[跳过] 文件不存在: {path}")
            continue
        if path.suffix.lower() != '.md':
            print(f"[跳过] 不支持的格式（仅 .md）: {path.name}")
            continue
        r = fix_headings(path, subject=args.subject, api_key=api_key, dry_run=args.dry_run)
        results.append(r)

    print(f"\n{'='*60}")
    print("汇总")
    print('='*60)
    for r in results:
        if r.get('error'):
            print(f"  {r['file']}: 失败 — {r['error']}")
        elif r.get('skipped'):
            print(f"  {r['file']}: 跳过 — {r['skipped']}")
        else:
            en_total = len(r.get('extraction_nodes', []))
            en_found = r.get('extraction_nodes_found', 0)
            print(f"  {r['file']}:")
            print(f"    non_content 删除: {r.get('non_content_removed', [])}")
            print(f"    修复后层级: {r.get('after_remap_dist', {})}")
            if en_total:
                print(f"    extraction_nodes: {en_found}/{en_total} 可找到")


if __name__ == '__main__':
    # Windows 控制台强制 UTF-8
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
