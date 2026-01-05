"""
创建测试用的Word文档
"""
from docx import Document

def create_test_doc():
    # 创建一个新的Word文档
    doc = Document()
    
    # 添加内容
    content = """林业经济学（双语）试题模板 - 单选题

请按照以下格式填写单选题：

单选题ID: sc_001
难度: medium
知识点: Merit goods definition
标签: basic,definition,public goods
中文题干: Merit goods在林业经济学中指的是什么？（）
英文题干: What does "Merit goods" refer to in forest economics? ()
A. 社会价值低于私人消费者价值的商品
A_en. Merchandise with social value lower than private consumer value
B. 社会价值超过私人消费者价值的商品
B_en. Merchandise with social value exceeding private consumer value
C. 仅具有私人价值的商品
C_en. Merchandise with private value only
D. 仅具有社会价值的商品
D_en. Merchandise with social value only
正确答案: B

是非题ID: tf_001
知识点: CVM methodology
标签: valuation,method,preference
中文题干: "Contingent valuation method"是一种了解消费者偏好的显示型（Revealed preference)方法。
英文题干: The Contingent Valuation Method (CVM) is a revealed preference approach for eliciting consumer preferences.
答案: F
解释: CVM是陈述型（Stated preference）方法，而非显示型（Revealed preference）方法。
English Explanation: CVM is a stated preference approach, not a revealed preference approach.

论述题ID: es_001
知识点: Types of externalities
标签: externality,classification,policy
中文题干: 有哪些不同类型的"外部性"？请列举出至少三种，并举例分析每种外部性分别是如何产生的？有何应对措施？
英文题干: What are the different types of externalities? Please identify at least three distinct categories and provide illustrative examples demonstrating how each type of externality arises. What policy interventions or remedial measures can be implemented to address them?
评分标准: 识别三种以上外部性类型 (5分); 每种类型提供具体例子 (5分); 分析产生机制 (3分); 提出应对措施 (2分)
English Scoring Guide: Identify three or more types of externalities (5 points); Provide specific examples for each type (5 points); Analyze generation mechanisms (3 points); Propose countermeasures (2 points)

计算题ID: calc_001
知识点: NPV calculation
标签: NPV,investment,decision
中文背景: 某村庄有一片荒地，如果自然更新，每30年可以产出价值10.9万元的木材，采伐成本为1万元。村委会现在要从以下投资决策中做出选择：
英文背景: A village possesses a tract of wasteland. Under natural regeneration, it would yield timber valued at ¥109,000 every 30 years, with harvesting costs of ¥10,000. The village committee must now choose among the following investment alternatives:
投资方案1: 投资20万元种植松树，每20年产出木材价值70万元的木材，采伐成本为6万元，每年的管理成本为1000元。
Investment Option 1: Invest ¥200,000 to establish a pine plantation, generating timber valued at ¥700,000 every 20 years, with harvesting costs of ¥60,000 and annual management costs of ¥1,000.
参数: 折现率:0.05; 时间系数:5年=1.3,10年=1.6,20年=2.6,30年=4.3; 公式:F=A*[(1+i)^n-1]/i
要求: 请计算不同投资决策的净现值，并根据净现值考虑选择哪种投资决策？#假如你是村委会的决策人，在投资决策时，除了净现值以外，你还将考虑哪些因素？分析在考虑这些因素后，你会如何改变决策？
English Requirements: Calculate the net present value (NPV) of each investment alternative and determine which option should be selected based on NPV analysis.#If you were the decision-maker for the village committee, what additional factors beyond NPV would you consider in the investment decision? Analyze how consideration of these factors might alter your decision."""

    # 添加段落
    for line in content.split('\n'):
        doc.add_paragraph(line)
    
    # 保存文档
    doc.save('D:\\code\\试卷\\test_questions_proper.docx')
    print("已创建测试文档: test_questions_proper.docx")

if __name__ == "__main__":
    create_test_doc()