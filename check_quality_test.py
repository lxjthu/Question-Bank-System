"""
套题质量检查测试脚本
手动运行：python check_quality_test.py
检查 2026春招 场次（session_id=3）全部题目：
  1. 题干与答案混淆/重叠
  2. 英文题干语法错误
"""

import sqlite3, json, re, os, sys, time
sys.stdout.reconfigure(encoding='utf-8')

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(
    api_key=os.environ['DEEPSEEK_API_KEY'],
    base_url='https://api.deepseek.com/v1',
)

DB_PATH = 'exam_system.db'
SESSION_ID = 3   # 2026春招
BATCH_SIZE = 8   # 每批发送题目数（控制 token）

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def strip(h):
    return re.sub(r'<[^>]+>', '', h or '').strip()

def load_questions(session_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    sets = cur.execute(
        'SELECT question_ids_json FROM interview_sets WHERE session_id=?', (session_id,)
    ).fetchall()
    all_qids = []
    for s in sets:
        all_qids.extend(json.loads(s['question_ids_json']))
    unique_qids = list(dict.fromkeys(all_qids))

    questions = []
    for qid in unique_qids:
        q = cur.execute(
            'SELECT question_id, question_type, content, content_en, answer, reference_answer '
            'FROM questions WHERE question_id=?', (qid,)
        ).fetchone()
        if q:
            questions.append({
                'question_id': q['question_id'],
                'question_type': q['question_type'],
                'content': strip(q['content']),
                'content_en': strip(q['content_en']) if q['content_en'] else '',
                'answer': q['answer'] or '',
                'reference_answer': strip(q['reference_answer']) if q['reference_answer'] else '',
            })
    conn.close()
    print(f'[加载] 共 {len(questions)} 道题目', flush=True)
    return questions

# ─── DeepSeek 检查 ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是专业的面试题库质检助手。你的任务是检查面试题目是否存在以下两类问题：

1. **题干答案混淆/重叠（stem_answer_confusion）**：
   - 题干中包含明显的答案提示或答案内容（如题干里出现"答案是…""包括…"等揭示性表述）
   - 参考答案与题干高度重复（超过50%内容重叠）
   - 参考答案为空但题干已暗含答案
   - 注意：简答题的参考答案正常应该比题干详细展开，这不算问题

2. **英文语法错误（grammar_error）**：
   - 仅检查 content_en 字段（英文题干），不检查英文参考答案
   - 检查语法错误（时态、主谓一致、冠词、介词等）
   - 检查表达不自然或不规范的学术英语
   - 对于空 content_en，跳过此类检查

对于没有问题的题目，issues 数组为空列表。
只返回 JSON，不输出任何其他内容。"""

USER_PROMPT_TEMPLATE = """请检查以下 {n} 道面试题目，返回 JSON 格式结果。

题目列表：
{questions_json}

返回格式（严格 JSON，不加 markdown 代码块）：
{{
  "results": [
    {{
      "question_id": "题目ID",
      "issues": [
        {{
          "type": "stem_answer_confusion 或 grammar_error",
          "field": "content 或 content_en 或 reference_answer",
          "description": "问题描述（中文）",
          "original": "原文（节选，不超过200字）",
          "suggested": "建议修改后的内容"
        }}
      ]
    }}
  ]
}}"""

def check_batch(questions_batch):
    """调用 DeepSeek 检查一批题目，返回 results 列表"""
    # 只发送检查需要的字段
    payload = [
        {
            'question_id': q['question_id'],
            'content': q['content'][:300],
            'content_en': q['content_en'][:300] if q['content_en'] else '',
            'reference_answer': q['reference_answer'][:400] if q['reference_answer'] else '（空）',
        }
        for q in questions_batch
    ]

    user_msg = USER_PROMPT_TEMPLATE.format(
        n=len(payload),
        questions_json=json.dumps(payload, ensure_ascii=False, indent=2)
    )

    resp = client.chat.completions.create(
        model='deepseek-chat',
        temperature=0.1,
        max_tokens=4096,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_msg},
        ],
    )
    raw = resp.choices[0].message.content.strip()
    # 去除可能的 markdown 代码块
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    try:
        data = json.loads(raw)
        return data.get('results', [])
    except json.JSONDecodeError as e:
        print(f'  [警告] JSON 解析失败: {e}')
        print(f'  原始返回: {raw[:500]}')
        return []

# ─── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    questions = load_questions(SESSION_ID)

    all_results = []
    batches = [questions[i:i+BATCH_SIZE] for i in range(0, len(questions), BATCH_SIZE)]
    print(f'[检查] 分 {len(batches)} 批，每批最多 {BATCH_SIZE} 道\n', flush=True)

    for bi, batch in enumerate(batches):
        print(f'  批次 {bi+1}/{len(batches)}（{len(batch)} 道）…', end=' ', flush=True)
        t0 = time.time()
        results = check_batch(batch)
        elapsed = time.time() - t0
        issues_count = sum(len(r.get('issues', [])) for r in results)
        print(f'发现 {issues_count} 个问题  ({elapsed:.1f}s)', flush=True)
        all_results.extend(results)
        time.sleep(0.5)  # 防止限速

    # ─── 汇总输出 ───────────────────────────────────────────────────────────────
    print('\n' + '='*70)
    print('检查结果汇总')
    print('='*70)

    issues_found = [r for r in all_results if r.get('issues')]
    print(f'有问题的题目：{len(issues_found)} / {len(all_results)} 道\n')

    for r in issues_found:
        qid = r['question_id']
        # 找原始题目
        orig = next((q for q in questions if q['question_id'] == qid), {})
        print(f'▶ {qid}')
        print(f'  题干: {orig.get("content","")[:100]}')
        if orig.get('content_en'):
            print(f'  EN  : {orig.get("content_en","")[:100]}')
        for issue in r['issues']:
            print(f'  [{issue["type"]}] 字段={issue["field"]}')
            print(f'  描述: {issue["description"]}')
            print(f'  原文: {issue.get("original","")[:120]}')
            print(f'  建议: {issue.get("suggested","")[:200]}')
        print()

    # 保存完整结果
    out_path = 'quality_check_result.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'session_id': SESSION_ID, 'total': len(all_results),
                   'issues_count': len(issues_found), 'results': all_results},
                  f, ensure_ascii=False, indent=2)
    print(f'[完成] 完整结果已保存至 {out_path}')


if __name__ == '__main__':
    main()
