"""
数据模型定义
"""
from datetime import datetime

# 存储题目数据
question_bank = {
    "single_choice_questions": [],
    "true_false_questions": [],
    "essay_questions": [],
    "calculation_questions": []
}

# 题目使用统计
question_usage = {}

# 保存的试卷组卷
saved_exams = {}

class Question:
    """题目基类"""
    def __init__(self, qid, qtype, difficulty="medium", knowledge_point="待设置", tags=None):
        self.id = qid
        self.type = qtype
        self.difficulty = difficulty
        self.knowledge_point = knowledge_point
        self.tags = tags or ["待分类"]
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

class SingleChoiceQuestion(Question):
    """单选题"""
    def __init__(self, qid, chinese_stem, english_stem, options, correct_answer, **kwargs):
        super().__init__(qid, "single_choice", **kwargs)
        self.chinese_stem = chinese_stem
        self.english_stem = english_stem
        self.options = options  # {"A": "选项A中文", "A_en": "选项A英文", "B": "选项B中文", ...}
        self.correct_answer = correct_answer

class TrueFalseQuestion(Question):
    """是非题"""
    def __init__(self, qid, chinese_stem, english_stem, correct_answer, explanation="", explanation_en="", **kwargs):
        super().__init__(qid, "true_false", **kwargs)
        self.chinese_stem = chinese_stem
        self.english_stem = english_stem
        self.correct_answer = correct_answer
        self.explanation = explanation
        self.explanation_en = explanation_en

class EssayQuestion(Question):
    """论述题"""
    def __init__(self, qid, chinese_stem, english_stem, scoring_guide, scoring_guide_en, **kwargs):
        super().__init__(qid, "essay", **kwargs)
        self.chinese_stem = chinese_stem
        self.english_stem = english_stem
        self.scoring_guide = scoring_guide  # 评分标准列表
        self.scoring_guide_en = scoring_guide_en

class CalculationQuestion(Question):
    """计算题"""
    def __init__(self, qid, context, alternatives=None, parameters=None, requirements=None, **kwargs):
        super().__init__(qid, "calculation", **kwargs)
        self.context = context  # {"chinese": "中文背景", "english": "英文背景"}
        self.alternatives = alternatives or []  # 选项列表
        self.parameters = parameters or {}  # 参数字典
        self.requirements = requirements or {"chinese": [], "english": []}  # 要求列表

class ExamPaper:
    """试卷类"""
    def __init__(self, school, academic_year, course_name, paper_type, question_types_config):
        self.school = school
        self.academic_year = academic_year
        self.course_name = course_name
        self.paper_type = paper_type
        self.question_types_config = question_types_config  # 各题型配置
        self.questions = {}  # 存储各题型的题目
        self.created_at = datetime.now()
        self.total_score = 0

    def add_questions(self, qtype, question_list):
        """添加题目到试卷"""
        self.questions[qtype] = question_list
        self._calculate_total_score()

    def _calculate_total_score(self):
        """计算总分"""
        total = 0
        for qtype, config in self.question_types_config.items():
            if qtype in self.questions:
                count = len(self.questions[qtype])
                score_per_question = config.get('score_per_question', 0)
                total += count * score_per_question
        self.total_score = total

    def generate_content(self):
        """生成试卷内容"""
        content = f"""{self.school}{self.academic_year}期末考试试卷
课程名称：《{self.course_name}（双语）》 （{self.paper_type}）卷
课程代号：B0600432
考试形式：闭卷、笔试
使用对象：

题号	一	二	三	四	五	六	七	总分	总分人
分值
得分

 -------------------------------------------------------------------------------

得分    评阅人


"""
        # 按题型生成试卷内容
        question_types_map = {
            'single_choice': '单选题',
            'true_false': '是非题',
            'essay': '论述题',
            'calculation': '计算题'
        }

        for qtype, qtype_name in question_types_map.items():
            if qtype in self.questions and qtype in self.question_types_config:
                q_config = self.question_types_config[qtype]
                count = len(self.questions[qtype])
                score_per_question = q_config.get('score_per_question', 0)

                if count > 0:
                    content += f"{qtype_name}：（共{count}题，每题{score_per_question}分，共{count * score_per_question}分）\n"

                    if qtype == 'single_choice':
                        content += '请将答案统一填写在答题栏里\n'
                        content += '题号\t' + '\t'.join([str(i+1) for i in range(count)]) + '\n'
                        content += '答案\t' + '\t'.join([' ' for _ in range(count)]) + '\n\n'

                    for i, q in enumerate(self.questions[qtype]):
                        if hasattr(q, 'chinese_stem'):
                            content += f"{i+1}. {q.chinese_stem}\n"
                        else:
                            content += f"{i+1}. {getattr(q, 'context', {}).get('chinese', '题目内容缺失')}\n"

                        if qtype == 'single_choice':
                            content += f"A. {getattr(q, 'options', {}).get('A', '')}\n"
                            content += f"B. {getattr(q, 'options', {}).get('B', '')}\n"
                            content += f"C. {getattr(q, 'options', {}).get('C', '')}\n"
                            content += f"D. {getattr(q, 'options', {}).get('D', '')}\n\n"
                        elif qtype == 'true_false':
                            content += f"正确答案: {getattr(q, 'correct_answer', '')}\n\n"
                        elif qtype == 'essay':
                            scoring_guide = getattr(q, 'scoring_guide', [])
                            content += f"评分标准: {'; '.join(scoring_guide) if isinstance(scoring_guide, list) else str(scoring_guide)}\n\n"
                        elif qtype == 'calculation':
                            context = getattr(q, 'context', {})
                            requirements = getattr(q, 'requirements', {})
                            content += f"背景: {context.get('chinese', '')}\n"
                            req_chinese = requirements.get('chinese', [])
                            content += f"要求: {'; '.join(req_chinese) if isinstance(req_chinese, list) else str(req_chinese)}\n\n"

        return content