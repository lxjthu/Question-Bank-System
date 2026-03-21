"""
PPT 文档 Layer 0 过渡页过滤测试
验证：
  A. _detect_doc_type 正确识别 PPT 型文档
  B. DeepSeek Layer 0 将过渡/封面幻灯片放入 non_content_texts
  C. 有实质知识内容的幻灯片进入 extraction_nodes
  D. 结果不影响教材型文档（回归）

用法：
    python -X utf8 test_ppt_layer0.py
"""
import sys, os, re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))
from rag_routes import (
    _clean_ocr_md,
    _extract_all_headings,
    _detect_doc_type,
    _clean_headings_with_ai,
    _parse_md_by_nodes,
)

SEP = "=" * 70


def get_key():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        for line in open(env_path, encoding='utf-8'):
            line = line.strip()
            if line.startswith('DEEPSEEK_API_KEY='):
                return line.split('=', 1)[1].strip()
    return os.environ.get('DEEPSEEK_API_KEY', '')


def main():
    ppt_file   = os.path.join(os.path.dirname(__file__), '知识点提取测试用例2-无明显章节标识.md')
    text_file  = os.path.join(os.path.dirname(__file__), '知识点提取测试用例.md')

    # ── A. _detect_doc_type 正确性检验 ────────────────────────────────────────
    print(SEP)
    print("A. _detect_doc_type 识别测试")

    ppt_raw = open(ppt_file, encoding='utf-8').read()
    ppt_cleaned, _ = _clean_ocr_md(ppt_raw)
    ppt_headings = _extract_all_headings(ppt_cleaned)
    ppt_doc_type = _detect_doc_type(ppt_headings)
    print(f"   PPT 文档 → doc_type = '{ppt_doc_type}' (预期: 'ppt')  "
          f"{'[OK]' if ppt_doc_type == 'ppt' else '[FAIL]'}")

    txt_raw = open(text_file, encoding='utf-8').read()
    txt_cleaned, _ = _clean_ocr_md(txt_raw)
    txt_headings = _extract_all_headings(txt_cleaned)
    txt_doc_type = _detect_doc_type(txt_headings)
    print(f"   教材文档 → doc_type = '{txt_doc_type}' (预期: 'textbook')  "
          f"{'[OK]' if txt_doc_type == 'textbook' else '[FAIL]'}")

    # ── B. Layer 0 AI 清洗（PPT） ─────────────────────────────────────────────
    print()
    print(SEP)
    print("B. DeepSeek Layer 0 清洗（PPT 文档）...")

    api_key = get_key()
    hierarchy = None

    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url='https://api.deepseek.com', timeout=60)
            hierarchy = _clean_headings_with_ai(ppt_headings, '农业项目管理', client)
            if hierarchy:
                print(f"   chapter_level   = {hierarchy['chapter_level']}  (预期: 1)")
                print(f"   section_level   = {hierarchy['section_level']}  (预期: 2)")
                nc = hierarchy['non_content_texts']
                en = hierarchy['extraction_nodes']
                print(f"   non_content_texts ({len(nc)} 个):")
                for t in sorted(nc):
                    print(f"     - {t}")
                print(f"   extraction_nodes ({len(en)} 个):")
                for t in en:
                    print(f"     - {t}")
            else:
                print("   [FAIL] Layer 0 返回 None（extraction_nodes 为空或解析失败）")
        except Exception as e:
            print(f"   Layer 0 调用失败: {type(e).__name__}: {e}")
    else:
        print("   无 API Key，跳过 API 调用（仅测试 A 和 D）")

    if hierarchy is None and not api_key:
        pass  # 后续验证跳过
    elif hierarchy is not None:
        # ── C. 验证过滤质量 ─────────────────────────────────────────────────────
        print()
        print(SEP)
        print("C. 过滤质量验证")

        nc = hierarchy['non_content_texts']
        en = hierarchy['extraction_nodes']

        # 应在 non_content_texts 中的标题（确定无实质内容的 H1 标题）
        # 注意：思考与讨论/小结 是 H2 子项，不进入两个列表（正确行为）
        EXPECTED_NON_CONTENT = [
            ('农业项目管理',                     '课程封面/标题页（H1）'),
            ('辞职回乡种地，我只坚持了半年',      '无关网络内容（H2，但嵌套在 non_content H1 下，间接过滤）'),
        ]
        print("   --- 预期放入 non_content_texts 的标题 ---")
        all_nc_ok = True
        for title, reason in EXPECTED_NON_CONTENT:
            found = title in nc
            status = '[OK]' if found else '[MISS]'
            if not found:
                all_nc_ok = False
            print(f"   {status} '{title}' ({reason})")

        # 应在 extraction_nodes 中的标题（有实质知识内容）
        EXPECTED_CONTENT = [
            '项目生命周期各阶段的 主要工作',
            '项目管理的过程组',
            '为什么项目需要有启动阶段',
            '项目启动阶段的主要工作',
            '项目资金的筹集',
            '项目规划阶段的主要工作',
            '项目实施阶段的主要工作',
            '项目收尾阶段的主要工作',
        ]
        print()
        print("   --- 预期放入 extraction_nodes 的实质内容幻灯片 ---")
        all_en_ok = True
        for title in EXPECTED_CONTENT:
            found = title in en
            status = '[OK]' if found else '[MISS]'
            if not found:
                all_en_ok = False
            print(f"   {status} '{title}'")

        # 确保过渡页不在 extraction_nodes 中
        print()
        print("   --- 确认过渡页未误入 extraction_nodes ---")
        SHOULD_NOT_BE_NODE = ['农业项目管理', '辞职回乡种地，我只坚持了半年', '小结']
        polluted = False
        for title in SHOULD_NOT_BE_NODE:
            in_nodes = title in en
            status = '[FAIL 误入]' if in_nodes else '[OK 未误入]'
            if in_nodes:
                polluted = True
            print(f"   {status} '{title}'")

        # 层级检验
        print()
        ch_ok  = hierarchy['chapter_level'] == 1
        sec_ok = hierarchy['section_level'] == 2
        print(f"   chapter_level == 1: {'[OK]' if ch_ok else '[FAIL]'}")
        print(f"   section_level == 2: {'[OK]' if sec_ok else '[FAIL]'}")

        # ── _parse_md_by_nodes 切分预览 ──────────────────────────────────────
        print()
        print(SEP)
        print("C2. _parse_md_by_nodes 切分预览（PPT 文档）")
        sections = _parse_md_by_nodes(ppt_cleaned, hierarchy)
        print(f"   共 {len(sections)} 个叶子节点")
        thin_count = sum(1 for s in sections if len(s['text']) < 80)
        print(f"   薄节点（text < 80字）: {thin_count} 个")
        print()
        for s in sections:
            flag = ' [薄]' if len(s['text']) < 80 else ''
            print(f"   [{s['num']:02d}] 父章:《{s['parent_chapter_name']}》| 节:《{s['chapter_name']}》"
                  f"| 小节:《{s['section_name']}》({len(s['text'])}字){flag}")

    # ── D. 教材型回归验证（确保现有逻辑未被破坏）────────────────────────────
    print()
    print(SEP)
    print("D. 教材型文档回归验证（使用硬编码 hierarchy，不依赖 API）")
    textbook_hierarchy = {
        'chapter_level': 2,
        'section_level': 3,
        'non_content_texts': {'【学习目标】', '这一框架的内涵是：', '小结', '关键词', '复习思考题', '主要参考文献'},
        'extraction_nodes': [
            '一、 农业经营制度的含义',
            '二、 农业经营制度变迁',
            '一、 农业经营主体',
            '二、 农业经营形式',
            '三、 农业经营制度的运行机制',
            '一、 新型农业经营体系',
            '二、 农业产业融合',
            '三、 农业社会化服务体系',
        ],
    }
    sections_tb = _parse_md_by_nodes(txt_cleaned, textbook_hierarchy)
    EXPECTED_TB_NODES = textbook_hierarchy['extraction_nodes']
    actual_tb_nodes = [s['section_name'] for s in sections_tb]
    all_tb_ok = True
    for exp in EXPECTED_TB_NODES:
        found = exp in actual_tb_nodes
        status = '[OK]' if found else '[MISS]'
        if not found:
            all_tb_ok = False
        print(f"   {status} {exp}")
    trap = '这一框架的内涵是：'
    trap_leaked = any(
        trap in s.get('chapter_name', '') or trap in s.get('parent_chapter_name', '')
        for s in sections_tb
    )
    print(f"   误标标题未污染章节名: {'[OK]' if not trap_leaked else '[FAIL]'}")
    print(f"   教材回归结果: {'[PASS]' if all_tb_ok and not trap_leaked else '[FAIL]'}")

    print()
    print(SEP)
    print("测试完成")


if __name__ == '__main__':
    main()
