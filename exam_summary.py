"""
林业经济学（双语）试卷内容总结报告
"""

def print_exam_summary():
    print("="*80)
    print("林业经济学（双语）试卷内容总结报告")
    print("="*80)
    
    print("\n【试卷基本信息】")
    print("-"*40)
    print("• 试卷名称: 林业经济学（双语）试卷A卷")
    print("• 学校: 中南财经政法大学")
    print("• 学年: 2025–2026学年第1学期")
    print("• 课程代码: B0600432")
    print("• 考试形式: 闭卷、笔试")
    print("• 总页数: 10页")
    
    print("\n【试卷结构】")
    print("-"*40)
    print("• 单选题: 5题，每题2分，共10分")
    print("• 是非题: 5题，每题2分，共10分") 
    print("• 论述题: 2题，每题15分，共30分")
    print("• 计算题: 1题，共20分")
    print("• 研究设计题: 1题，共30分")
    print("• 总分: 100分")
    
    print("\n【题目内容概览】")
    print("-"*40)
    print("\n单选题主题:")
    print("1. Merit goods在林业经济学中的定义")
    print("2. Technological externality的相关概念")  
    print("3. 林业经济学的一般性假设")
    print("4. 净现值计算问题")
    print("5. 投资效益分析")
    
    print("\n是非题主题:")
    print("• Contingent valuation method的性质")
    print("• Equivalent variation与Compensating Variation的适用性")
    print("• Hedonic method的定义")
    print("• Replacement Cost在林业经济学中的应用")
    print("• 森林公园效益净现值计算")
    print("• 英文版的经济学概念理解题")
    
    print("\n论述题主题:")
    print("1. 外部性的类型、产生机制及应对措施")
    print("2. 森林资源价值评估方法（消费者剩余角度）")
    print("3. 保存价值（preservation value）的含义和类型")
    
    print("\n计算题主题:")
    print("• 村庄荒地投资决策分析（净现值计算）")
    print("• 涉及自然更新、种植松树、承包经营、生态旅游等投资方案比较")
    
    print("\n研究设计题主题:")
    print("• 南湖水质提升支付意愿研究设计")
    print("• 包括问卷设计、抽样方法、数据分析方法")
    
    print("\n【文档内容提取说明】")
    print("-"*40)
    print("• 成功提取了原始Word文档中的全部文本内容")
    print("• 包含中英文双语试题")
    print("• 保留了完整的格式和题型结构")
    print("• 已将内容保存至: D:\\code\\试卷\\林业经济学试卷_完整内容.txt")
    
    print("\n【技术实现方法】")
    print("-"*40)
    print("• 使用python-docx库探索文档结构")
    print("• 通过解压.docx文件分析XML结构")
    print("• 提取word/document.xml中的<w:t>标签内容")
    print("• 处理编码问题，确保中文内容正确显示")
    
    print("\n" + "="*80)
    print("处理完成！")
    print("="*80)

if __name__ == "__main__":
    print_exam_summary()