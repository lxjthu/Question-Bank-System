"""
Web服务器用于处理试题管理系统
包含Word文档到CSV的转换功能
"""

from flask import Flask, request, jsonify, send_file, render_template_string
import json
import os
import tempfile
from werkzeug.utils import secure_filename
from word_to_csv_converter import WordToCsvConverter
from datetime import datetime


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

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

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {'docx'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    """返回主页面"""
    html_content = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>林业经济学（双语）试题管理系统</title>
    <style>
        body {
            font-family: 'Microsoft YaHei', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        h1 {
            text-align: center;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }
        
        .tab-container {
            margin-top: 20px;
        }
        
        .tab-buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .tab-btn {
            padding: 10px 20px;
            background: #3498db;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }
        
        .tab-btn.active {
            background: #2980b9;
        }
        
        .tab-content {
            display: none;
            padding: 20px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background: #fafafa;
        }
        
        .tab-content.active {
            display: block;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #34495e;
        }
        
        input, select, textarea {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            box-sizing: border-box;
        }
        
        textarea {
            height: 100px;
            resize: vertical;
        }
        
        .btn {
            padding: 10px 20px;
            background: #3498db;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            margin-right: 10px;
        }
        
        .btn:hover {
            background: #2980b9;
        }
        
        .btn-success {
            background: #27ae60;
        }
        
        .btn-success:hover {
            background: #219653;
        }
        
        .btn-danger {
            background: #e74c3c;
        }
        
        .btn-danger:hover {
            background: #c0392b;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        
        th, td {
            border: 1px solid #ddd;
            padding: 12px;
            text-align: left;
        }
        
        th {
            background-color: #3498db;
            color: white;
        }
        
        tr:nth-child(even) {
            background-color: #f2f2f2;
        }
        
        .action-buttons {
            display: flex;
            gap: 5px;
        }
        
        .file-input {
            margin-bottom: 15px;
        }
        
        .usage-info {
            background: #e8f4fd;
            padding: 10px;
            border-radius: 4px;
            margin-top: 10px;
        }
        
        .question-preview {
            background: #f9f9f9;
            padding: 15px;
            border-left: 4px solid #3498db;
            margin: 10px 0;
        }
        
        .word-template-section {
            background: #fff3cd;
            padding: 15px;
            border-radius: 4px;
            margin: 15px 0;
            border-left: 4px solid #ffc107;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>林业经济学（双语）试题管理系统</h1>
        
        <div class="tab-container">
            <div class="tab-buttons">
                <button class="tab-btn active" onclick="showTab('question-bank')">题库管理</button>
                <button class="tab-btn" onclick="showTab('exam-generation')">试卷生成</button>
                <button class="tab-btn" onclick="showTab('template')">模板下载</button>
            </div>
            
            <!-- 题库管理标签页 -->
            <div id="question-bank" class="tab-content active">
                <h2>题库管理</h2>
                
                <div class="form-group">
                    <label>添加新题目类型：</label>
                    <select id="questionType">
                        <option value="single_choice">单选题</option>
                        <option value="true_false">是非题</option>
                        <option value="essay">论述题</option>
                        <option value="calculation">计算题</option>
                    </select>
                    <button class="btn" onclick="addNewQuestion()">添加题目</button>
                </div>
                
                <div class="form-group">
                    <label>导入题目（Word文档）：</label>
                    <input type="file" id="wordFile" accept=".docx" class="file-input">
                    <button class="btn btn-success" onclick="convertWordToCsv()">转换为题库</button>
                    <div id="conversionStatus" style="margin-top: 10px;"></div>
                </div>
                
                <div class="form-group">
                    <label>导出题库：</label>
                    <button class="btn" onclick="exportQuestionBank()">导出为JSON</button>
                    <button class="btn" onclick="exportQuestionBankAsCsv()">导出为CSV</button>
                </div>
                
                <div id="questionForm" style="display: none;">
                    <h3>添加新题目</h3>
                    <div id="singleChoiceForm" style="display: none;">
                        <div class="form-group">
                            <label>ID：</label>
                            <input type="text" id="scId" value="">
                        </div>
                        <div class="form-group">
                            <label>难度：</label>
                            <select id="scDifficulty">
                                <option value="easy">简单</option>
                                <option value="medium" selected>中等</option>
                                <option value="hard">困难</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>中文题干：</label>
                            <textarea id="scChineseStem"></textarea>
                        </div>
                        <div class="form-group">
                            <label>英文题干：</label>
                            <textarea id="scEnglishStem"></textarea>
                        </div>
                        <div class="form-group">
                            <label>选项A（中文）：</label>
                            <input type="text" id="scOptionACh">
                        </div>
                        <div class="form-group">
                            <label>选项A（英文）：</label>
                            <input type="text" id="scOptionAEn">
                        </div>
                        <div class="form-group">
                            <label>选项B（中文）：</label>
                            <input type="text" id="scOptionBCh">
                        </div>
                        <div class="form-group">
                            <label>选项B（英文）：</label>
                            <input type="text" id="scOptionBEn">
                        </div>
                        <div class="form-group">
                            <label>选项C（中文）：</label>
                            <input type="text" id="scOptionCCh">
                        </div>
                        <div class="form-group">
                            <label>选项C（英文）：</label>
                            <input type="text" id="scOptionCEn">
                        </div>
                        <div class="form-group">
                            <label>选项D（中文）：</label>
                            <input type="text" id="scOptionDCh">
                        </div>
                        <div class="form-group">
                            <label>选项D（英文）：</label>
                            <input type="text" id="scOptionDEn">
                        </div>
                        <div class="form-group">
                            <label>正确答案：</label>
                            <select id="scCorrectAnswer">
                                <option value="A">A</option>
                                <option value="B">B</option>
                                <option value="C">C</option>
                                <option value="D">D</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>知识点：</label>
                            <input type="text" id="scKnowledgePoint">
                        </div>
                        <div class="form-group">
                            <label>标签（逗号分隔）：</label>
                            <input type="text" id="scTags">
                        </div>
                    </div>
                    
                    <div id="trueFalseForm" style="display: none;">
                        <div class="form-group">
                            <label>ID：</label>
                            <input type="text" id="tfId" value="">
                        </div>
                        <div class="form-group">
                            <label>中文题干：</label>
                            <textarea id="tfChineseStem"></textarea>
                        </div>
                        <div class="form-group">
                            <label>英文题干：</label>
                            <textarea id="tfEnglishStem"></textarea>
                        </div>
                        <div class="form-group">
                            <label>正确答案：</label>
                            <select id="tfCorrectAnswer">
                                <option value="T">正确(T)</option>
                                <option value="F">错误(F)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>中文解释：</label>
                            <textarea id="tfExplanationCh"></textarea>
                        </div>
                        <div class="form-group">
                            <label>英文解释：</label>
                            <textarea id="tfExplanationEn"></textarea>
                        </div>
                        <div class="form-group">
                            <label>知识点：</label>
                            <input type="text" id="tfKnowledgePoint">
                        </div>
                        <div class="form-group">
                            <label>标签（逗号分隔）：</label>
                            <input type="text" id="tfTags">
                        </div>
                    </div>
                    
                    <div id="essayForm" style="display: none;">
                        <div class="form-group">
                            <label>ID：</label>
                            <input type="text" id="esId" value="">
                        </div>
                        <div class="form-group">
                            <label>中文题干：</label>
                            <textarea id="esChineseStem"></textarea>
                        </div>
                        <div class="form-group">
                            <label>英文题干：</label>
                            <textarea id="esEnglishStem"></textarea>
                        </div>
                        <div class="form-group">
                            <label>中文评分标准：</label>
                            <textarea id="esScoringGuideCh"></textarea>
                        </div>
                        <div class="form-group">
                            <label>英文评分标准：</label>
                            <textarea id="esScoringGuideEn"></textarea>
                        </div>
                        <div class="form-group">
                            <label>知识点：</label>
                            <input type="text" id="esKnowledgePoint">
                        </div>
                        <div class="form-group">
                            <label>标签（逗号分隔）：</label>
                            <input type="text" id="esTags">
                        </div>
                    </div>
                    
                    <div id="calculationForm" style="display: none;">
                        <div class="form-group">
                            <label>ID：</label>
                            <input type="text" id="calcId" value="">
                        </div>
                        <div class="form-group">
                            <label>中文背景：</label>
                            <textarea id="calcContextCh"></textarea>
                        </div>
                        <div class="form-group">
                            <label>英文背景：</label>
                            <textarea id="calcContextEn"></textarea>
                        </div>
                        <div class="form-group">
                            <label>参数：</label>
                            <input type="text" id="calcParameters">
                        </div>
                        <div class="form-group">
                            <label>中文要求：</label>
                            <textarea id="calcRequirementsCh"></textarea>
                        </div>
                        <div class="form-group">
                            <label>英文要求：</label>
                            <textarea id="calcRequirementsEn"></textarea>
                        </div>
                        <div class="form-group">
                            <label>知识点：</label>
                            <input type="text" id="calcKnowledgePoint">
                        </div>
                        <div class="form-group">
                            <label>标签（逗号分隔）：</label>
                            <input type="text" id="calcTags">
                        </div>
                    </div>
                    
                    <button class="btn btn-success" onclick="saveNewQuestion()">保存题目</button>
                    <button class="btn" onclick="cancelAddQuestion()">取消</button>
                </div>
                
                <h3>现有题目列表</h3>
                <table id="questionTable">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>题型</th>
                            <th>难度</th>
                            <th>知识点</th>
                            <th>使用次数</th>
                            <th>最后使用</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody id="questionTableBody">
                        <!-- 动态填充 -->
                    </tbody>
                </table>
            </div>
            
            <!-- 试卷生成标签页 -->
            <div id="exam-generation" class="tab-content">
                <h2>试卷生成</h2>

                <div class="form-group">
                    <label>学校：</label>
                    <input type="text" id="school" value="中南财经政法大学">
                </div>

                <div class="form-group">
                    <label>学年：</label>
                    <input type="text" id="academicYear" value="2025–2026学年第1学期">
                </div>

                <div class="form-group">
                    <label>课程名称：</label>
                    <input type="text" id="courseName" value="林业经济学">
                </div>

                <div class="form-group">
                    <label>试卷类型：</label>
                    <select id="paperType">
                        <option value="A">A卷</option>
                        <option value="B">B卷</option>
                        <option value="C">C卷</option>
                        <option value="D">D卷</option>
                    </select>
                </div>

                <h3>题型配置</h3>

                <div class="form-group">
                    <label>单选题：</label>
                    <input type="number" id="scCount" value="5" min="0" style="width: 60px;" oninput="calculateTotalScore()"> 题 ×
                    <input type="number" id="scScore" value="2" min="1" style="width: 60px;" oninput="calculateTotalScore()"> 分/题
                </div>

                <div class="form-group">
                    <label>是非题：</label>
                    <input type="number" id="tfCount" value="5" min="0" style="width: 60px;" oninput="calculateTotalScore()"> 题 ×
                    <input type="number" id="tfScore" value="2" min="1" style="width: 60px;" oninput="calculateTotalScore()"> 分/题
                </div>

                <div class="form-group">
                    <label>论述题：</label>
                    <input type="number" id="esCount" value="2" min="0" style="width: 60px;" oninput="calculateTotalScore()"> 题 ×
                    <input type="number" id="esScore" value="15" min="1" style="width: 60px;" oninput="calculateTotalScore()"> 分/题
                </div>

                <div class="form-group">
                    <label>计算题：</label>
                    <input type="number" id="calcCount" value="1" min="0" style="width: 60px;" oninput="calculateTotalScore()"> 题 ×
                    <input type="number" id="calcScore" value="20" min="1" style="width: 60px;" oninput="calculateTotalScore()"> 分/题
                </div>

                <div class="form-group">
                    <label style="color: #27ae60; font-weight: bold;">试卷总分：<span id="totalScore">100</span> 分</label>
                </div>

                <div style="margin: 20px 0;">
                    <h3>手动选择题目</h3>
                    <div class="form-group">
                        <label>搜索题目：</label>
                        <input type="text" id="searchKeyword" placeholder="输入关键词搜索题目">
                        <select id="searchType">
                            <option value="">所有题型</option>
                            <option value="single_choice">单选题</option>
                            <option value="true_false">是非题</option>
                            <option value="essay">论述题</option>
                            <option value="calculation">计算题</option>
                        </select>
                        <button class="btn" onclick="searchQuestions()">搜索</button>
                    </div>

                    <div id="searchResults" style="margin-top: 15px; max-height: 300px; overflow-y: auto; border: 1px solid #ddd; padding: 10px; display: none;">
                        <h4>搜索结果</h4>
                        <div id="searchResultsContent"></div>
                    </div>

                    <div style="margin-top: 15px;">
                        <h4>已选题目</h4>
                        <div id="selectedQuestions" style="border: 1px solid #ddd; padding: 10px; min-height: 100px;">
                            <p>暂无已选题目</p>
                        </div>
                    </div>
                </div>

                <div style="margin: 20px 0;">
                    <h3>试卷管理</h3>
                    <div class="form-group">
                        <label>试卷名称：</label>
                        <input type="text" id="examName" placeholder="输入试卷名称">
                        <button class="btn btn-success" onclick="saveExam()">保存试卷</button>
                        <button class="btn" onclick="loadSavedExams()">加载试卷</button>
                    </div>

                    <div id="savedExamsList" style="margin-top: 15px; display: none;">
                        <h4>保存的试卷</h4>
                        <div id="savedExamsContent"></div>
                    </div>
                </div>

                <button class="btn btn-success" onclick="generateExam()">生成试卷</button>
                <button class="btn" onclick="previewExam()">预览试卷</button>
                <button class="btn btn-success" onclick="autoGenerateExam()">一键自动组卷</button>

                <div id="examPreview" style="margin-top: 20px; display: none;">
                    <h3>试卷预览</h3>
                    <div id="examContent" style="white-space: pre-wrap; background: #f9f9f9; padding: 15px; border: 1px solid #ddd;"></div>
                    <button class="btn" onclick="downloadExam()">下载试卷 (Word)</button>
                </div>
            </div>
            
            <!-- 模板下载标签页 -->
            <div id="template" class="tab-content">
                <h2>模板下载</h2>
                
                <div class="word-template-section">
                    <h3>Word文档模板说明</h3>
                    <p>您可以下载以下Word模板来编写题目，然后通过"题库管理"页面的导入功能将题目添加到题库中。</p>
                    <p><strong>模板包含以下题型格式：</strong></p>
                    <ul>
                        <li>单选题：包含中文/英文题干、四个选项、正确答案</li>
                        <li>是非题：包含中文/英文题干、正确答案、解释</li>
                        <li>论述题：包含中文/英文题干、评分标准</li>
                        <li>计算题：包含背景、参数、要求</li>
                    </ul>
                </div>
                
                <div class="form-group">
                    <button class="btn btn-success" onclick="downloadTemplate('single_choice')">下载单选题Word模板</button>
                    <button class="btn btn-success" onclick="downloadTemplate('true_false')">下载是非题Word模板</button>
                    <button class="btn btn-success" onclick="downloadTemplate('essay')">下载论述题Word模板</button>
                    <button class="btn btn-success" onclick="downloadTemplate('calculation')">下载计算题Word模板</button>
                </div>
                
                <h3>Word文档格式要求</h3>
                <p>为了正确转换，Word文档需要遵循以下格式：</p>
                <ol>
                    <li><strong>单选题</strong>：题干以"单选题ID:"开始，后面跟题目内容，四个选项标记为"A.", "B.", "C.", "D."，最后是"正确答案:"</li>
                    <li><strong>是非题</strong>：题干以"是非题ID:"开始，后面跟题目内容，然后是"答案:"和"解释:"</li>
                    <li><strong>论述题</strong>：题干以"论述题ID:"开始，后面跟题目内容和"评分标准:"</li>
                    <li><strong>计算题</strong>：题干以"计算题ID:"开始，后面跟背景信息、参数和要求</li>
                </ol>
            </div>
        </div>
    </div>

    <script>
        // 全局变量存储题目数据
        let questionBank = {
            single_choice_questions: [],
            true_false_questions: [],
            essay_questions: [],
            calculation_questions: []
        };
        
        // 题目使用统计
        let questionUsage = {};
        
        // 当前编辑的题目索引
        let currentEditIndex = -1;
        let currentEditType = '';
        
        // 显示指定标签页
        function showTab(tabId) {
            // 隐藏所有标签页
            const tabs = document.querySelectorAll('.tab-content');
            tabs.forEach(tab => tab.classList.remove('active'));
            
            // 移除所有按钮的active类
            const buttons = document.querySelectorAll('.tab-btn');
            buttons.forEach(btn => btn.classList.remove('active'));
            
            // 显示选中的标签页
            document.getElementById(tabId).classList.add('active');
            
            // 激活对应的按钮
            event.target.classList.add('active');
        }
        
        // 根据题型显示相应表单
        function addNewQuestion() {
            document.getElementById('questionForm').style.display = 'block';
            
            // 隐藏所有表单
            document.getElementById('singleChoiceForm').style.display = 'none';
            document.getElementById('trueFalseForm').style.display = 'none';
            document.getElementById('essayForm').style.display = 'none';
            document.getElementById('calculationForm').style.display = 'none';
            
            const questionType = document.getElementById('questionType').value;
            
            // 显示对应表单
            if (questionType === 'single_choice') {
                document.getElementById('singleChoiceForm').style.display = 'block';
                // 生成默认ID
                document.getElementById('scId').value = 'sc_' + (questionBank.single_choice_questions.length + 1).toString().padStart(3, '0');
                document.getElementById('scKnowledgePoint').value = '';
                document.getElementById('scTags').value = '';
            } else if (questionType === 'true_false') {
                document.getElementById('trueFalseForm').style.display = 'block';
                document.getElementById('tfId').value = 'tf_' + (questionBank.true_false_questions.length + 1).toString().padStart(3, '0');
                document.getElementById('tfKnowledgePoint').value = '';
                document.getElementById('tfTags').value = '';
            } else if (questionType === 'essay') {
                document.getElementById('essayForm').style.display = 'block';
                document.getElementById('esId').value = 'es_' + (questionBank.essay_questions.length + 1).toString().padStart(3, '0');
                document.getElementById('esKnowledgePoint').value = '';
                document.getElementById('esTags').value = '';
            } else if (questionType === 'calculation') {
                document.getElementById('calculationForm').style.display = 'block';
                document.getElementById('calcId').value = 'calc_' + (questionBank.calculation_questions.length + 1).toString().padStart(3, '0');
                document.getElementById('calcKnowledgePoint').value = '';
                document.getElementById('calcTags').value = '';
            }
            
            currentEditIndex = -1; // 重置编辑索引
            currentEditType = questionType;
        }
        
        // 取消添加题目
        function cancelAddQuestion() {
            document.getElementById('questionForm').style.display = 'none';
        }
        
        // 保存新题目
        function saveNewQuestion() {
            const questionType = document.getElementById('questionType').value;
            
            if (questionType === 'single_choice') {
                const question = {
                    id: document.getElementById('scId').value || 'sc_' + (questionBank.single_choice_questions.length + 1).toString().padStart(3, '0'),
                    type: 'single_choice',
                    difficulty: document.getElementById('scDifficulty').value,
                    chinese_stem: document.getElementById('scChineseStem').value,
                    english_stem: document.getElementById('scEnglishStem').value,
                    options: {
                        A: document.getElementById('scOptionACh').value,
                        A_en: document.getElementById('scOptionAEn').value,
                        B: document.getElementById('scOptionBCh').value,
                        B_en: document.getElementById('scOptionBEn').value,
                        C: document.getElementById('scOptionCCh').value,
                        C_en: document.getElementById('scOptionCEn').value,
                        D: document.getElementById('scOptionDCh').value,
                        D_en: document.getElementById('scOptionDEn').value
                    },
                    correct_answer: document.getElementById('scCorrectAnswer').value,
                    knowledge_point: document.getElementById('scKnowledgePoint').value || '待设置',
                    tags: document.getElementById('scTags').value ? document.getElementById('scTags').value.split(',').map(tag => tag.trim()) : ['待分类']
                };
                
                if (currentEditIndex >= 0) {
                    // 编辑现有题目
                    questionBank.single_choice_questions[currentEditIndex] = question;
                } else {
                    // 添加新题目
                    questionBank.single_choice_questions.push(question);
                }
                
            } else if (questionType === 'true_false') {
                const question = {
                    id: document.getElementById('tfId').value || 'tf_' + (questionBank.true_false_questions.length + 1).toString().padStart(3, '0'),
                    type: 'true_false',
                    chinese_stem: document.getElementById('tfChineseStem').value,
                    english_stem: document.getElementById('tfEnglishStem').value,
                    correct_answer: document.getElementById('tfCorrectAnswer').value,
                    explanation: document.getElementById('tfExplanationCh').value,
                    explanation_en: document.getElementById('tfExplanationEn').value,
                    knowledge_point: document.getElementById('tfKnowledgePoint').value || '待设置',
                    tags: document.getElementById('tfTags').value ? document.getElementById('tfTags').value.split(',').map(tag => tag.trim()) : ['待分类']
                };
                
                if (currentEditIndex >= 0) {
                    questionBank.true_false_questions[currentEditIndex] = question;
                } else {
                    questionBank.true_false_questions.push(question);
                }
                
            } else if (questionType === 'essay') {
                const question = {
                    id: document.getElementById('esId').value || 'es_' + (questionBank.essay_questions.length + 1).toString().padStart(3, '0'),
                    type: 'essay',
                    chinese_stem: document.getElementById('esChineseStem').value,
                    english_stem: document.getElementById('esEnglishStem').value,
                    scoring_guide: document.getElementById('esScoringGuideCh').value.split('\\n'),
                    scoring_guide_en: document.getElementById('esScoringGuideEn').value.split('\\n'),
                    knowledge_point: document.getElementById('esKnowledgePoint').value || '待设置',
                    tags: document.getElementById('esTags').value ? document.getElementById('esTags').value.split(',').map(tag => tag.trim()) : ['待分类']
                };
                
                if (currentEditIndex >= 0) {
                    questionBank.essay_questions[currentEditIndex] = question;
                } else {
                    questionBank.essay_questions.push(question);
                }
                
            } else if (questionType === 'calculation') {
                const question = {
                    id: document.getElementById('calcId').value || 'calc_' + (questionBank.calculation_questions.length + 1).toString().padStart(3, '0'),
                    type: 'calculation',
                    context: {
                        chinese: document.getElementById('calcContextCh').value,
                        english: document.getElementById('calcContextEn').value
                    },
                    parameters: document.getElementById('calcParameters').value,
                    requirements: {
                        chinese: document.getElementById('calcRequirementsCh').value,
                        english: document.getElementById('calcRequirementsEn').value
                    },
                    knowledge_point: document.getElementById('calcKnowledgePoint').value || '待设置',
                    tags: document.getElementById('calcTags').value ? document.getElementById('calcTags').value.split(',').map(tag => tag.trim()) : ['待分类']
                };
                
                if (currentEditIndex >= 0) {
                    questionBank.calculation_questions[currentEditIndex] = question;
                } else {
                    questionBank.calculation_questions.push(question);
                }
            }
            
            // 重置表单和隐藏
            document.getElementById('questionForm').style.display = 'none';
            refreshQuestionTable();
            
            alert('题目保存成功！');
        }
        
        // 编辑题目
        function editQuestion(qtype, index) {
            currentEditIndex = index;
            currentEditType = qtype;
            
            // 显示表单
            document.getElementById('questionForm').style.display = 'block';
            
            // 隐藏所有表单，显示对应表单
            document.getElementById('singleChoiceForm').style.display = 'none';
            document.getElementById('trueFalseForm').style.display = 'none';
            document.getElementById('essayForm').style.display = 'none';
            document.getElementById('calculationForm').style.display = 'none';
            
            let question;
            if (qtype === 'single_choice') {
                question = questionBank.single_choice_questions[index];
                document.getElementById('questionType').value = 'single_choice';
                document.getElementById('singleChoiceForm').style.display = 'block';
                
                document.getElementById('scId').value = question.id;
                document.getElementById('scDifficulty').value = question.difficulty;
                document.getElementById('scChineseStem').value = question.chinese_stem;
                document.getElementById('scEnglishStem').value = question.english_stem;
                document.getElementById('scOptionACh').value = question.options.A;
                document.getElementById('scOptionAEn').value = question.options.A_en;
                document.getElementById('scOptionBCh').value = question.options.B;
                document.getElementById('scOptionBEn').value = question.options.B_en;
                document.getElementById('scOptionCCh').value = question.options.C;
                document.getElementById('scOptionCEn').value = question.options.C_en;
                document.getElementById('scOptionDCh').value = question.options.D;
                document.getElementById('scOptionDEn').value = question.options.D_en;
                document.getElementById('scCorrectAnswer').value = question.correct_answer;
                document.getElementById('scKnowledgePoint').value = question.knowledge_point;
                document.getElementById('scTags').value = question.tags.join(', ');
                
            } else if (qtype === 'true_false') {
                question = questionBank.true_false_questions[index];
                document.getElementById('questionType').value = 'true_false';
                document.getElementById('trueFalseForm').style.display = 'block';
                
                document.getElementById('tfId').value = question.id;
                document.getElementById('tfChineseStem').value = question.chinese_stem;
                document.getElementById('tfEnglishStem').value = question.english_stem;
                document.getElementById('tfCorrectAnswer').value = question.correct_answer;
                document.getElementById('tfExplanationCh').value = question.explanation;
                document.getElementById('tfExplanationEn').value = question.explanation_en;
                document.getElementById('tfKnowledgePoint').value = question.knowledge_point;
                document.getElementById('tfTags').value = question.tags.join(', ');
                
            } else if (qtype === 'essay') {
                question = questionBank.essay_questions[index];
                document.getElementById('questionType').value = 'essay';
                document.getElementById('essayForm').style.display = 'block';
                
                document.getElementById('esId').value = question.id;
                document.getElementById('esChineseStem').value = question.chinese_stem;
                document.getElementById('esEnglishStem').value = question.english_stem;
                document.getElementById('esScoringGuideCh').value = question.scoring_guide.join('\\n');
                document.getElementById('esScoringGuideEn').value = question.scoring_guide_en.join('\\n');
                document.getElementById('esKnowledgePoint').value = question.knowledge_point;
                document.getElementById('esTags').value = question.tags.join(', ');
                
            } else if (qtype === 'calculation') {
                question = questionBank.calculation_questions[index];
                document.getElementById('questionType').value = 'calculation';
                document.getElementById('calculationForm').style.display = 'block';
                
                document.getElementById('calcId').value = question.id;
                document.getElementById('calcContextCh').value = question.context.chinese;
                document.getElementById('calcContextEn').value = question.context.english;
                document.getElementById('calcParameters').value = question.parameters;
                document.getElementById('calcRequirementsCh').value = question.requirements.chinese;
                document.getElementById('calcRequirementsEn').value = question.requirements.english;
                document.getElementById('calcKnowledgePoint').value = question.knowledge_point;
                document.getElementById('calcTags').value = question.tags.join(', ');
            }
        }
        
        // 删除题目
        function deleteQuestion(qtype, index) {
            if (confirm('确定要删除这道题目吗？')) {
                if (qtype === 'single_choice') {
                    questionBank.single_choice_questions.splice(index, 1);
                } else if (qtype === 'true_false') {
                    questionBank.true_false_questions.splice(index, 1);
                } else if (qtype === 'essay') {
                    questionBank.essay_questions.splice(index, 1);
                } else if (qtype === 'calculation') {
                    questionBank.calculation_questions.splice(index, 1);
                }
                
                refreshQuestionTable();
                alert('题目删除成功！');
            }
        }
        
        // 刷新题目表格
        function refreshQuestionTable() {
            fetch('/api/questions')
                .then(response => response.json())
                .then(data => {
                    questionBank = data;
                    
                    const tbody = document.getElementById('questionTableBody');
                    tbody.innerHTML = '';
                    
                    // 单选题
                    questionBank.single_choice_questions.forEach((q, index) => {
                        const usage = questionUsage[q.id] || { count: 0, last_used: '从未使用' };
                        const row = tbody.insertRow();
                        row.innerHTML = `
                            <td>${q.id}</td>
                            <td>单选题</td>
                            <td>${q.difficulty}</td>
                            <td>${q.knowledge_point}</td>
                            <td>${usage.count}</td>
                            <td>${usage.last_used}</td>
                            <td class="action-buttons">
                                <button class="btn" onclick="editQuestion('single_choice', ${index})">编辑</button>
                                <button class="btn btn-danger" onclick="deleteQuestion('single_choice', ${index})">删除</button>
                            </td>
                        `;
                    });
                    
                    // 是非题
                    questionBank.true_false_questions.forEach((q, index) => {
                        const usage = questionUsage[q.id] || { count: 0, last_used: '从未使用' };
                        const row = tbody.insertRow();
                        row.innerHTML = `
                            <td>${q.id}</td>
                            <td>是非题</td>
                            <td>-</td>
                            <td>${q.knowledge_point}</td>
                            <td>${usage.count}</td>
                            <td>${usage.last_used}</td>
                            <td class="action-buttons">
                                <button class="btn" onclick="editQuestion('true_false', ${index})">编辑</button>
                                <button class="btn btn-danger" onclick="deleteQuestion('true_false', ${index})">删除</button>
                            </td>
                        `;
                    });
                    
                    // 论述题
                    questionBank.essay_questions.forEach((q, index) => {
                        const usage = questionUsage[q.id] || { count: 0, last_used: '从未使用' };
                        const row = tbody.insertRow();
                        row.innerHTML = `
                            <td>${q.id}</td>
                            <td>论述题</td>
                            <td>-</td>
                            <td>${q.knowledge_point}</td>
                            <td>${usage.count}</td>
                            <td>${usage.last_used}</td>
                            <td class="action-buttons">
                                <button class="btn" onclick="editQuestion('essay', ${index})">编辑</button>
                                <button class="btn btn-danger" onclick="deleteQuestion('essay', ${index})">删除</button>
                            </td>
                        `;
                    });
                    
                    // 计算题
                    questionBank.calculation_questions.forEach((q, index) => {
                        const usage = questionUsage[q.id] || { count: 0, last_used: '从未使用' };
                        const row = tbody.insertRow();
                        row.innerHTML = `
                            <td>${q.id}</td>
                            <td>计算题</td>
                            <td>-</td>
                            <td>${q.knowledge_point}</td>
                            <td>${usage.count}</td>
                            <td>${usage.last_used}</td>
                            <td class="action-buttons">
                                <button class="btn" onclick="editQuestion('calculation', ${index})">编辑</button>
                                <button class="btn btn-danger" onclick="deleteQuestion('calculation', ${index})">删除</button>
                            </td>
                        `;
                    });
                })
                .catch(error => console.error('Error:', error));
        }
        
        // 导出题库为JSON
        function exportQuestionBank() {
            fetch('/api/export/json')
                .then(response => response.blob())
                .then(blob => {
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'question_bank.json';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);
                });
        }
        
        // 导出题库为CSV
        function exportQuestionBankAsCsv() {
            fetch('/api/export/csv')
                .then(response => response.blob())
                .then(blob => {
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'question_bank.csv';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);
                });
        }
        
        // 转换Word文档为CSV
        function convertWordToCsv() {
            const fileInput = document.getElementById('wordFile');
            if (fileInput.files.length === 0) {
                alert('请选择一个Word文档');
                return;
            }
            
            const file = fileInput.files[0];
            if (!file.name.toLowerCase().endsWith('.docx')) {
                alert('请选择.docx格式的Word文档');
                return;
            }
            
            const formData = new FormData();
            formData.append('file', file);
            
            document.getElementById('conversionStatus').innerHTML = '正在上传和转换...';
            
            fetch('/api/convert-word', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('conversionStatus').innerHTML = `<span style="color: green;">转换成功！${data.message}</span>`;
                    refreshQuestionTable(); // 刷新题目列表

                    // 显示警告信息
                    if (data.warnings && data.warnings.length > 0) {
                        const warningMessage = "发现以下缺失部分：\\n\\n" + data.warnings.join("\\n") + "\\n\\n如确认则显示空白。";
                        alert(warningMessage);
                    } else {
                        alert(data.message);
                    }
                } else {
                    document.getElementById('conversionStatus').innerHTML = `<span style="color: red;">转换失败：${data.message}</span>`;
                    alert('转换失败：' + data.message);
                }
            })
            .catch(error => {
                document.getElementById('conversionStatus').innerHTML = `<span style="color: red;">转换出错：${error}</span>`;
            });
        }
        
        // 预览试卷
        function previewExam() {
            const examConfig = {
                school: document.getElementById('school').value,
                academic_year: document.getElementById('academicYear').value,
                course_name: document.getElementById('courseName').value,
                paper_type: document.getElementById('paperType').value,
                question_types: {
                    single_choice: {
                        count: parseInt(document.getElementById('scCount').value),
                        score_per_question: parseInt(document.getElementById('scScore').value)
                    },
                    true_false: {
                        count: parseInt(document.getElementById('tfCount').value),
                        score_per_question: parseInt(document.getElementById('tfScore').value)
                    },
                    essay: {
                        count: parseInt(document.getElementById('esCount').value),
                        score_per_question: parseInt(document.getElementById('esScore').value)
                    },
                    calculation: {
                        count: parseInt(document.getElementById('calcCount').value),
                        score_per_question: parseInt(document.getElementById('calcScore').value)
                    }
                }
            };

            fetch('/api/generate-exam', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(examConfig)
            })
            .then(response => response.json())
            .then(data => {
                document.getElementById('examContent').textContent = data.exam_content;
                document.getElementById('examPreview').style.display = 'block';
            })
            .catch(error => {
                alert('生成试卷失败: ' + error);
            });
        }

        // 搜索题目
        function searchQuestions() {
            const keyword = document.getElementById('searchKeyword').value;
            const questionType = document.getElementById('searchType').value;

            const searchParams = {
                keyword: keyword,
                type: questionType
            };

            fetch('/api/search-questions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(searchParams)
            })
            .then(response => response.json())
            .then(data => {
                displaySearchResults(data);
            })
            .catch(error => {
                alert('搜索题目失败: ' + error);
            });
        }

        // 显示搜索结果
        function displaySearchResults(results) {
            const container = document.getElementById('searchResultsContent');
            container.innerHTML = '';

            let hasResults = false;

            // 显示单选题
            if (results.single_choice_questions && results.single_choice_questions.length > 0) {
                hasResults = true;
                const scDiv = document.createElement('div');
                scDiv.innerHTML = '<h5>单选题</h5>';
                results.single_choice_questions.forEach((q, index) => {
                    const questionDiv = document.createElement('div');
                    questionDiv.className = 'question-preview';
                    questionDiv.innerHTML = `
                        <div>
                            <strong>${q.id}</strong> - ${q.chinese_stem.substring(0, 50)}...
                            <button class="btn" onclick="selectQuestion('${q.type}', '${q.id}', ${index}, 'single_choice_questions')">选择</button>
                        </div>
                    `;
                    scDiv.appendChild(questionDiv);
                });
                container.appendChild(scDiv);
            }

            // 显示是非题
            if (results.true_false_questions && results.true_false_questions.length > 0) {
                hasResults = true;
                const tfDiv = document.createElement('div');
                tfDiv.innerHTML = '<h5>是非题</h5>';
                results.true_false_questions.forEach((q, index) => {
                    const questionDiv = document.createElement('div');
                    questionDiv.className = 'question-preview';
                    questionDiv.innerHTML = `
                        <div>
                            <strong>${q.id}</strong> - ${q.chinese_stem.substring(0, 50)}...
                            <button class="btn" onclick="selectQuestion('${q.type}', '${q.id}', ${index}, 'true_false_questions')">选择</button>
                        </div>
                    `;
                    tfDiv.appendChild(questionDiv);
                });
                container.appendChild(tfDiv);
            }

            // 显示论述题
            if (results.essay_questions && results.essay_questions.length > 0) {
                hasResults = true;
                const esDiv = document.createElement('div');
                esDiv.innerHTML = '<h5>论述题</h5>';
                results.essay_questions.forEach((q, index) => {
                    const questionDiv = document.createElement('div');
                    questionDiv.className = 'question-preview';
                    questionDiv.innerHTML = `
                        <div>
                            <strong>${q.id}</strong> - ${q.chinese_stem.substring(0, 50)}...
                            <button class="btn" onclick="selectQuestion('${q.type}', '${q.id}', ${index}, 'essay_questions')">选择</button>
                        </div>
                    `;
                    esDiv.appendChild(questionDiv);
                });
                container.appendChild(esDiv);
            }

            // 显示计算题
            if (results.calculation_questions && results.calculation_questions.length > 0) {
                hasResults = true;
                const calcDiv = document.createElement('div');
                calcDiv.innerHTML = '<h5>计算题</h5>';
                results.calculation_questions.forEach((q, index) => {
                    const questionDiv = document.createElement('div');
                    questionDiv.className = 'question-preview';
                    questionDiv.innerHTML = `
                        <div>
                            <strong>${q.id}</strong> - ${q.context.chinese.substring(0, 50)}...
                            <button class="btn" onclick="selectQuestion('${q.type}', '${q.id}', ${index}, 'calculation_questions')">选择</button>
                        </div>
                    `;
                    calcDiv.appendChild(questionDiv);
                });
                container.appendChild(calcDiv);
            }

            if (!hasResults) {
                container.innerHTML = '<p>未找到匹配的题目</p>';
            }

            document.getElementById('searchResults').style.display = 'block';
        }

        // 选择题目
        function selectQuestion(qtype, qid, index, questionListName) {
            // 获取题目信息
            let question = null;
            if (questionListName === 'single_choice_questions') {
                question = questionBank.single_choice_questions.find(q => q.id === qid);
            } else if (questionListName === 'true_false_questions') {
                question = questionBank.true_false_questions.find(q => q.id === qid);
            } else if (questionListName === 'essay_questions') {
                question = questionBank.essay_questions.find(q => q.id === qid);
            } else if (questionListName === 'calculation_questions') {
                question = questionBank.calculation_questions.find(q => q.id === qid);
            }

            if (question) {
                // 添加到已选题目列表
                const selectedContainer = document.getElementById('selectedQuestions');

                // 检查是否已存在
                const existingItem = selectedContainer.querySelector(`[data-question-id="${qid}"]`);
                if (existingItem) {
                    alert('该题目已添加到试卷中');
                    return;
                }

                const questionDiv = document.createElement('div');
                questionDiv.className = 'question-preview';
                questionDiv.setAttribute('data-question-id', qid);
                questionDiv.setAttribute('data-question-type', qtype);

                let questionText = '';
                if (qtype === 'single_choice') {
                    questionText = `${question.chinese_stem.substring(0, 50)}...`;
                } else if (qtype === 'true_false') {
                    questionText = `${question.chinese_stem.substring(0, 50)}...`;
                } else if (qtype === 'essay') {
                    questionText = `${question.chinese_stem.substring(0, 50)}...`;
                } else if (qtype === 'calculation') {
                    questionText = `${question.context.chinese.substring(0, 50)}...`;
                }

                questionDiv.innerHTML = `
                    <div>
                        <strong>${question.id}</strong> - ${questionText}
                        <button class="btn btn-danger" onclick="removeSelectedQuestion('${qid}')">移除</button>
                    </div>
                `;

                if (selectedContainer.innerHTML.includes('暂无已选题目')) {
                    selectedContainer.innerHTML = '';
                }

                selectedContainer.appendChild(questionDiv);
            }
        }

        // 移除已选题目
        function removeSelectedQuestion(qid) {
            const selectedContainer = document.getElementById('selectedQuestions');
            const itemToRemove = selectedContainer.querySelector(`[data-question-id="${qid}"]`);
            if (itemToRemove) {
                itemToRemove.remove();

                // 如果没有已选题目，显示提示
                if (selectedContainer.children.length === 0) {
                    selectedContainer.innerHTML = '<p>暂无已选题目</p>';
                }
            }
        }

        // 保存试卷
        function saveExam() {
            const examName = document.getElementById('examName').value;
            if (!examName) {
                alert('请输入试卷名称');
                return;
            }

            // 获取已选题目
            const selectedQuestions = [];
            const selectedContainer = document.getElementById('selectedQuestions');
            const questionItems = selectedContainer.querySelectorAll('[data-question-id]');

            questionItems.forEach(item => {
                const qid = item.getAttribute('data-question-id');
                const qtype = item.getAttribute('data-question-type');

                let question = null;
                if (qtype === 'single_choice') {
                    question = questionBank.single_choice_questions.find(q => q.id === qid);
                } else if (qtype === 'true_false') {
                    question = questionBank.true_false_questions.find(q => q.id === qid);
                } else if (qtype === 'essay') {
                    question = questionBank.essay_questions.find(q => q.id === qid);
                } else if (qtype === 'calculation') {
                    question = questionBank.calculation_questions.find(q => q.id === qid);
                }

                if (question) {
                    selectedQuestions.push({
                        id: question.id,
                        type: question.type,
                        data: question
                    });
                }
            });

            const examData = {
                name: examName,
                config: {
                    school: document.getElementById('school').value,
                    academic_year: document.getElementById('academicYear').value,
                    course_name: document.getElementById('courseName').value,
                    paper_type: document.getElementById('paperType').value,
                    question_types: {
                        single_choice: {
                            count: parseInt(document.getElementById('scCount').value),
                            score_per_question: parseInt(document.getElementById('scScore').value)
                        },
                        true_false: {
                            count: parseInt(document.getElementById('tfCount').value),
                            score_per_question: parseInt(document.getElementById('tfScore').value)
                        },
                        essay: {
                            count: parseInt(document.getElementById('esCount').value),
                            score_per_question: parseInt(document.getElementById('esScore').value)
                        },
                        calculation: {
                            count: parseInt(document.getElementById('calcCount').value),
                            score_per_question: parseInt(document.getElementById('calcScore').value)
                        }
                    }
                },
                questions: selectedQuestions
            };

            fetch('/api/save-exam', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ exam_data: examData })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('试卷保存成功！');
                } else {
                    alert('试卷保存失败：' + data.message);
                }
            })
            .catch(error => {
                alert('保存试卷失败: ' + error);
            });
        }

        // 加载保存的试卷列表
        function loadSavedExams() {
            fetch('/api/list-saved-exams')
                .then(response => response.json())
                .then(data => {
                    displaySavedExams(data);
                })
                .catch(error => {
                    alert('加载保存的试卷失败: ' + error);
                });
        }

        // 显示保存的试卷列表
        function displaySavedExams(exams) {
            const container = document.getElementById('savedExamsContent');
            container.innerHTML = '';

            if (exams.length > 0) {
                exams.forEach(exam => {
                    const examDiv = document.createElement('div');
                    examDiv.className = 'question-preview';
                    examDiv.innerHTML = `
                        <div>
                            <strong>${exam.name}</strong> - ${new Date(exam.created_at).toLocaleString()}
                            <button class="btn" onclick="loadSpecificExam('${exam.id}')">加载</button>
                            <button class="btn btn-danger" onclick="deleteSavedExam('${exam.id}')">删除</button>
                        </div>
                    `;
                    container.appendChild(examDiv);
                });
                document.getElementById('savedExamsList').style.display = 'block';
            } else {
                container.innerHTML = '<p>暂无保存的试卷</p>';
                document.getElementById('savedExamsList').style.display = 'block';
            }
        }

        // 加载特定试卷
        function loadSpecificExam(examId) {
            fetch(`/api/load-exam/${examId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success !== false) {
                        // 填充基本信息
                        document.getElementById('school').value = data.config.school || '中南财经政法大学';
                        document.getElementById('academicYear').value = data.config.academic_year || '2025–2026学年第1学期';
                        document.getElementById('courseName').value = data.config.course_name || '林业经济学';
                        document.getElementById('paperType').value = data.config.paper_type || 'A';

                        // 填充题型配置
                        document.getElementById('scCount').value = data.config.question_types.single_choice.count || 5;
                        document.getElementById('scScore').value = data.config.question_types.single_choice.score_per_question || 2;
                        document.getElementById('tfCount').value = data.config.question_types.true_false.count || 5;
                        document.getElementById('tfScore').value = data.config.question_types.true_false.score_per_question || 2;
                        document.getElementById('esCount').value = data.config.question_types.essay.count || 2;
                        document.getElementById('esScore').value = data.config.question_types.essay.score_per_question || 15;
                        document.getElementById('calcCount').value = data.config.question_types.calculation.count || 1;
                        document.getElementById('calcScore').value = data.config.question_types.calculation.score_per_question || 20;

                        // 填充已选题目
                        const selectedContainer = document.getElementById('selectedQuestions');
                        selectedContainer.innerHTML = '';

                        if (data.questions && data.questions.length > 0) {
                            data.questions.forEach(q => {
                                const questionDiv = document.createElement('div');
                                questionDiv.className = 'question-preview';
                                questionDiv.setAttribute('data-question-id', q.id);
                                questionDiv.setAttribute('data-question-type', q.type);

                                let questionText = '';
                                if (q.type === 'single_choice') {
                                    questionText = `${q.data.chinese_stem.substring(0, 50)}...`;
                                } else if (q.type === 'true_false') {
                                    questionText = `${q.data.chinese_stem.substring(0, 50)}...`;
                                } else if (q.type === 'essay') {
                                    questionText = `${q.data.chinese_stem.substring(0, 50)}...`;
                                } else if (q.type === 'calculation') {
                                    questionText = `${q.data.context.chinese.substring(0, 50)}...`;
                                }

                                questionDiv.innerHTML = `
                                    <div>
                                        <strong>${q.id}</strong> - ${questionText}
                                        <button class="btn btn-danger" onclick="removeSelectedQuestion('${q.id}')">移除</button>
                                    </div>
                                `;

                                selectedContainer.appendChild(questionDiv);
                            });
                        } else {
                            selectedContainer.innerHTML = '<p>暂无已选题目</p>';
                        }

                        alert('试卷加载成功！');
                    } else {
                        alert('加载试卷失败：' + data.message);
                    }
                })
                .catch(error => {
                    alert('加载试卷失败: ' + error);
                });
        }

        // 删除保存的试卷
        function deleteSavedExam(examId) {
            if (confirm('确定要删除这个试卷吗？')) {
                fetch(`/api/delete-exam/${examId}`, {
                    method: 'DELETE'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('试卷删除成功！');
                        loadSavedExams(); // 重新加载列表
                    } else {
                        alert('删除试卷失败：' + data.message);
                    }
                })
                .catch(error => {
                    alert('删除试卷失败: ' + error);
                });
            }
        }
        
        // 存储生成的试卷
        let generatedExam = null;

        // 当前预览模式
        let currentPreviewMode = 'chinese'; // chinese, english, bilingual, chinese_no_answer, bilingual_with_answer

        // 生成试卷
        function generateExam() {
            // 获取已选题目
            const selectedQuestions = [];
            const selectedContainer = document.getElementById('selectedQuestions');
            const questionItems = selectedContainer.querySelectorAll('[data-question-id]');

            questionItems.forEach(item => {
                const qid = item.getAttribute('data-question-id');
                const qtype = item.getAttribute('data-question-type');

                let question = null;
                if (qtype === 'single_choice') {
                    question = questionBank.single_choice_questions.find(q => q.id === qid);
                } else if (qtype === 'true_false') {
                    question = questionBank.true_false_questions.find(q => q.id === qid);
                } else if (qtype === 'essay') {
                    question = questionBank.essay_questions.find(q => q.id === qid);
                } else if (qtype === 'calculation') {
                    question = questionBank.calculation_questions.find(q => q.id === qid);
                }

                if (question) {
                    selectedQuestions.push({
                        id: question.id,
                        type: question.type,
                        data: question
                    });
                }
            });

            const examConfig = {
                school: document.getElementById('school').value,
                academic_year: document.getElementById('academicYear').value,
                course_name: document.getElementById('courseName').value,
                paper_type: document.getElementById('paperType').value,
                question_types: {
                    single_choice: {
                        count: parseInt(document.getElementById('scCount').value),
                        score_per_question: parseInt(document.getElementById('scScore').value)
                    },
                    true_false: {
                        count: parseInt(document.getElementById('tfCount').value),
                        score_per_question: parseInt(document.getElementById('tfScore').value)
                    },
                    essay: {
                        count: parseInt(document.getElementById('esCount').value),
                        score_per_question: parseInt(document.getElementById('esScore').value)
                    },
                    calculation: {
                        count: parseInt(document.getElementById('calcCount').value),
                        score_per_question: parseInt(document.getElementById('calcScore').value)
                    }
                },
                selected_questions: selectedQuestions  // 添加手动选择的题目
            };

            fetch('/api/generate-exam', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(examConfig)
            })
            .then(response => response.json())
            .then(data => {
                // 保存生成的试卷数据
                generatedExam = {
                    header: `${examConfig.school}\n${examConfig.academic_year}\n${examConfig.course_name} 试卷（${examConfig.paper_type}卷）\n总分：${calculateTotalScore()}分`,
                    question_types: examConfig.question_types,
                    questions: processQuestionsForPreview(selectedQuestions, examConfig)
                };

                displayExamPreview(generatedExam, 'chinese'); // 默认显示中文版
                document.getElementById('examPreview').style.display = 'block';
            })
            .catch(error => {
                alert('生成试卷失败: ' + error);
            });
        }

        // 预览试卷
        function previewExam() {
            // 获取已选题目
            const selectedQuestions = [];
            const selectedContainer = document.getElementById('selectedQuestions');
            const questionItems = selectedContainer.querySelectorAll('[data-question-id]');

            questionItems.forEach(item => {
                const qid = item.getAttribute('data-question-id');
                const qtype = item.getAttribute('data-question-type');

                let question = null;
                if (qtype === 'single_choice') {
                    question = questionBank.single_choice_questions.find(q => q.id === qid);
                } else if (qtype === 'true_false') {
                    question = questionBank.true_false_questions.find(q => q.id === qid);
                } else if (qtype === 'essay') {
                    question = questionBank.essay_questions.find(q => q.id === qid);
                } else if (qtype === 'calculation') {
                    question = questionBank.calculation_questions.find(q => q.id === qid);
                }

                if (question) {
                    selectedQuestions.push({
                        id: question.id,
                        type: question.type,
                        data: question
                    });
                }
            });

            const examConfig = {
                school: document.getElementById('school').value,
                academic_year: document.getElementById('academicYear').value,
                course_name: document.getElementById('courseName').value,
                paper_type: document.getElementById('paperType').value,
                question_types: {
                    single_choice: {
                        count: parseInt(document.getElementById('scCount').value),
                        score_per_question: parseInt(document.getElementById('scScore').value)
                    },
                    true_false: {
                        count: parseInt(document.getElementById('tfCount').value),
                        score_per_question: parseInt(document.getElementById('tfScore').value)
                    },
                    essay: {
                        count: parseInt(document.getElementById('esCount').value),
                        score_per_question: parseInt(document.getElementById('esScore').value)
                    },
                    calculation: {
                        count: parseInt(document.getElementById('calcCount').value),
                        score_per_question: parseInt(document.getElementById('calcScore').value)
                    }
                },
                selected_questions: selectedQuestions  // 添加手动选择的题目
            };

            fetch('/api/generate-exam', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(examConfig)
            })
            .then(response => response.json())
            .then(data => {
                // 保存生成的试卷数据
                generatedExam = {
                    header: `${examConfig.school}\n${examConfig.academic_year}\n${examConfig.course_name} 试卷（${examConfig.paper_type}卷）\n总分：${calculateTotalScore()}分`,
                    question_types: examConfig.question_types,
                    questions: processQuestionsForPreview(selectedQuestions, examConfig)
                };

                displayExamPreview(generatedExam, 'chinese'); // 默认显示中文版
                document.getElementById('examPreview').style.display = 'block';
            })
            .catch(error => {
                alert('预览试卷失败: ' + error);
            });
        }

        // 处理题目数据用于预览
        function processQuestionsForPreview(selectedQuestions, examConfig) {
            const result = {
                single_choice: [],
                true_false: [],
                essay: [],
                calculation: []
            };

            // 添加手动选择的题目
            selectedQuestions.forEach(q => {
                if (q.type === 'single_choice') {
                    result.single_choice.push(q.data);
                } else if (q.type === 'true_false') {
                    result.true_false.push(q.data);
                } else if (q.type === 'essay') {
                    result.essay.push(q.data);
                } else if (q.type === 'calculation') {
                    result.calculation.push(q.data);
                }
            });

            // 从题库中补充剩余题目
            const scRemaining = Math.max(0, examConfig.question_types.single_choice.count - result.single_choice.length);
            if (scRemaining > 0) {
                const available = questionBank.single_choice_questions.filter(q =>
                    !selectedQuestions.some(sq => sq.id === q.id)
                );
                const additional = available.slice(0, scRemaining);
                result.single_choice = result.single_choice.concat(additional);
            }

            const tfRemaining = Math.max(0, examConfig.question_types.true_false.count - result.true_false.length);
            if (tfRemaining > 0) {
                const available = questionBank.true_false_questions.filter(q =>
                    !selectedQuestions.some(sq => sq.id === q.id)
                );
                const additional = available.slice(0, tfRemaining);
                result.true_false = result.true_false.concat(additional);
            }

            const esRemaining = Math.max(0, examConfig.question_types.essay.count - result.essay.length);
            if (esRemaining > 0) {
                const available = questionBank.essay_questions.filter(q =>
                    !selectedQuestions.some(sq => sq.id === q.id)
                );
                const additional = available.slice(0, esRemaining);
                result.essay = result.essay.concat(additional);
            }

            const calcRemaining = Math.max(0, examConfig.question_types.calculation.count - result.calculation.length);
            if (calcRemaining > 0) {
                const available = questionBank.calculation_questions.filter(q =>
                    !selectedQuestions.some(sq => sq.id === q.id)
                );
                const additional = available.slice(0, calcRemaining);
                result.calculation = result.calculation.concat(additional);
            }

            return result;
        }

        // 显示试卷预览
        function displayExamPreview(exam, mode) {
            currentPreviewMode = mode;
            let content = exam.header + '\n\n';

            // 单选题
            if (exam.questions.single_choice.length > 0) {
                content += `一、单选题（每题${exam.question_types.single_choice.score_per_question}分，共${exam.questions.single_choice.length * exam.question_types.single_choice.score_per_question}分）\n\n`;

                exam.questions.single_choice.forEach((q, index) => {
                    content += formatQuestion(q, 'single_choice', index + 1, mode, index, 'single_choice');
                    content += '\n\n';
                });
            }

            // 是非题
            if (exam.questions.true_false.length > 0) {
                const score = exam.question_types.true_false.score_per_question;
                const totalScore = exam.questions.true_false.length * score;
                content += `二、是非题（每题${score}分，共${totalScore}分）\n\n`;

                exam.questions.true_false.forEach((q, index) => {
                    content += formatQuestion(q, 'true_false', index + 1, mode, index, 'true_false');
                    content += '\n\n';
                });
            }

            // 论述题
            if (exam.questions.essay.length > 0) {
                const score = exam.question_types.essay.score_per_question;
                const totalScore = exam.questions.essay.length * score;
                content += `三、论述题（每题${score}分，共${totalScore}分）\n\n`;

                exam.questions.essay.forEach((q, index) => {
                    content += formatQuestion(q, 'essay', index + 1, mode, index, 'essay');
                    content += '\n\n';
                });
            }

            // 计算题
            if (exam.questions.calculation.length > 0) {
                const score = exam.question_types.calculation.score_per_question;
                const totalScore = exam.questions.calculation.length * score;
                content += `四、计算题（每题${score}分，共${totalScore}分）\n\n`;

                exam.questions.calculation.forEach((q, index) => {
                    content += formatQuestion(q, 'calculation', index + 1, mode, index, 'calculation');
                    content += '\n\n';
                });
            }

            // 添加预览控制按钮
            const previewControls = `
<div style="margin-top: 20px; padding: 10px; background: #e8f4fd; border-radius: 4px;">
    <strong>预览模式：</strong>
    <button class="btn" onclick="changePreviewMode('chinese')">全中文</button>
    <button class="btn" onclick="changePreviewMode('english')">全英文</button>
    <button class="btn" onclick="changePreviewMode('bilingual')">中英对照</button>
    <button class="btn" onclick="changePreviewMode('chinese_no_answer')">不展示答案</button>
    <button class="btn" onclick="changePreviewMode('bilingual_with_answer')">展示答案</button>
    <button class="btn btn-success" onclick="downloadExamAsWord()">导出Word</button>
</div>
            `;

            document.getElementById('examContent').innerHTML = `<div>${content.replace(/\n/g, '<br>')}</div>${previewControls}`;
        }

        // 格式化题目显示
        function formatQuestion(question, qType, index, mode, questionIndex, questionCategory) {
            let result = `${index}. `;

            switch(qType) {
                case 'single_choice':
                    if (mode === 'chinese') {
                        result += `${question.chinese_stem}\n`;
                        result += `A. ${question.options.A}\n`;
                        result += `B. ${question.options.B}\n`;
                        result += `C. ${question.options.C}\n`;
                        result += `D. ${question.options.D}\n`;
                        if (mode !== 'chinese_no_answer') {
                            result += `正确答案：${question.correct_answer}`;
                        }
                    } else if (mode === 'english') {
                        result += `${question.english_stem}\n`;
                        result += `A. ${question.options.A_en}\n`;
                        result += `B. ${question.options.B_en}\n`;
                        result += `C. ${question.options.C_en}\n`;
                        result += `D. ${question.options.D_en}\n`;
                        if (mode !== 'chinese_no_answer') {
                            result += `Correct Answer: ${question.correct_answer}`;
                        }
                    } else if (mode === 'bilingual') {
                        result += `${question.chinese_stem}\n`;
                        result += `${question.english_stem}\n`;
                        result += `A. ${question.options.A} / ${question.options.A_en}\n`;
                        result += `B. ${question.options.B} / ${question.options.B_en}\n`;
                        result += `C. ${question.options.C} / ${question.options.C_en}\n`;
                        result += `D. ${question.options.D} / ${question.options.D_en}\n`;
                        if (mode !== 'chinese_no_answer') {
                            result += `正确答案：${question.correct_answer} / Correct Answer: ${question.correct_answer}`;
                        }
                    } else if (mode === 'chinese_no_answer') {
                        result += `${question.chinese_stem}\n`;
                        result += `A. ${question.options.A}\n`;
                        result += `B. ${question.options.B}\n`;
                        result += `C. ${question.options.C}\n`;
                        result += `D. ${question.options.D}\n`;
                    } else if (mode === 'bilingual_with_answer') {
                        result += `${question.chinese_stem}\n`;
                        result += `${question.english_stem}\n`;
                        result += `A. ${question.options.A} / ${question.options.A_en}\n`;
                        result += `B. ${question.options.B} / ${question.options.B_en}\n`;
                        result += `C. ${question.options.C} / ${question.options.C_en}\n`;
                        result += `D. ${question.options.D} / ${question.options.D_en}\n`;
                        result += `正确答案：${question.correct_answer} / Correct Answer: ${question.correct_answer}`;
                        result += `\n解释：${question.explanation || ''} / Explanation: ${question.explanation_en || ''}`;
                    }
                    break;

                case 'true_false':
                    if (mode === 'chinese') {
                        result += `${question.chinese_stem}\n`;
                        if (mode !== 'chinese_no_answer') {
                            result += `答案：${question.correct_answer === 'T' ? '正确' : '错误'} (${question.correct_answer})`;
                        }
                    } else if (mode === 'english') {
                        result += `${question.english_stem}\n`;
                        if (mode !== 'chinese_no_answer') {
                            result += `Answer: ${question.correct_answer}`;
                        }
                    } else if (mode === 'bilingual') {
                        result += `${question.chinese_stem}\n`;
                        result += `${question.english_stem}\n`;
                        if (mode !== 'chinese_no_answer') {
                            result += `答案：${question.correct_answer === 'T' ? '正确' : '错误'} / Answer: ${question.correct_answer}`;
                        }
                    } else if (mode === 'chinese_no_answer') {
                        result += `${question.chinese_stem}\n`;
                    } else if (mode === 'bilingual_with_answer') {
                        result += `${question.chinese_stem}\n`;
                        result += `${question.english_stem}\n`;
                        result += `答案：${question.correct_answer === 'T' ? '正确' : '错误'} / Answer: ${question.correct_answer}`;
                        result += `\n解释：${question.explanation} / Explanation: ${question.explanation_en}`;
                    }
                    break;

                case 'essay':
                    if (mode === 'chinese') {
                        result += `${question.chinese_stem}`;
                    } else if (mode === 'english') {
                        result += `${question.english_stem}`;
                    } else if (mode === 'bilingual') {
                        result += `${question.chinese_stem}\n`;
                        result += `${question.english_stem}`;
                    } else if (mode === 'chinese_no_answer' || mode === 'bilingual_with_answer') {
                        result += `${question.chinese_stem}\n`;
                        result += `${question.english_stem}`;
                        if (mode === 'bilingual_with_answer') {
                            result += `\n评分标准：${question.scoring_guide.join('; ')} / Scoring Guide: ${question.scoring_guide_en.join('; ')}`;
                        }
                    }
                    break;

                case 'calculation':
                    if (mode === 'chinese') {
                        result += `${question.context.chinese}`;
                        if (question.alternatives) {
                            question.alternatives.forEach((alt, i) => {
                                result += `\n${i+1}. ${alt.description.chinese}`;
                            });
                        }
                        if (question.parameters) {
                            result += `\n参数: ${JSON.stringify(question.parameters)}`;
                        }
                        question.requirements.chinese.forEach(req => {
                            result += `\n要求: ${req}`;
                        });
                    } else if (mode === 'english') {
                        result += `${question.context.english}`;
                        if (question.alternatives) {
                            question.alternatives.forEach((alt, i) => {
                                result += `\n${i+1}. ${alt.description.english}`;
                            });
                        }
                        if (question.parameters) {
                            result += `\nParameters: ${JSON.stringify(question.parameters)}`;
                        }
                        question.requirements.english.forEach(req => {
                            result += `\nRequirements: ${req}`;
                        });
                    } else if (mode === 'bilingual') {
                        result += `${question.context.chinese}\n`;
                        result += `${question.context.english}\n`;
                        if (question.alternatives) {
                            question.alternatives.forEach((alt, i) => {
                                result += `${i+1}. ${alt.description.chinese} / ${alt.description.english}\n`;
                            });
                        }
                        if (question.parameters) {
                            result += `参数: ${JSON.stringify(question.parameters)} / Parameters: ${JSON.stringify(question.parameters)}\n`;
                        }
                        question.requirements.chinese.forEach((req, i) => {
                            result += `要求: ${req} / Requirements: ${question.requirements.english[i] || ''}\n`;
                        });
                    } else if (mode === 'chinese_no_answer' || mode === 'bilingual_with_answer') {
                        result += `${question.context.chinese}\n`;
                        result += `${question.context.english}\n`;
                        if (question.alternatives) {
                            question.alternatives.forEach((alt, i) => {
                                result += `${i+1}. ${alt.description.chinese} / ${alt.description.english}\n`;
                            });
                        }
                        if (question.parameters) {
                            result += `参数: ${JSON.stringify(question.parameters)} / Parameters: ${JSON.stringify(question.parameters)}\n`;
                        }
                        question.requirements.chinese.forEach((req, i) => {
                            result += `要求: ${req} / Requirements: ${question.requirements.english[i] || ''}\n`;
                        });
                    }
                    break;
            }

            // 添加替换按钮
            result += `\n<button class="btn" onclick="replaceQuestion('${questionCategory}', ${questionIndex})">替换此题</button>`;

            return result;
        }

        // 切换预览模式
        function changePreviewMode(mode) {
            if (generatedExam) {
                displayExamPreview(generatedExam, mode);
            }
        }

        // 替换题目
        function replaceQuestion(questionCategory, questionIndex) {
            // 根据题目类型获取可用的替换题目列表
            let availableQuestions = [];
            let currentQuestion = null;

            switch(questionCategory) {
                case 'single_choice':
                    availableQuestions = questionBank.single_choice_questions;
                    currentQuestion = generatedExam.questions.single_choice[questionIndex];
                    break;
                case 'true_false':
                    availableQuestions = questionBank.true_false_questions;
                    currentQuestion = generatedExam.questions.true_false[questionIndex];
                    break;
                case 'essay':
                    availableQuestions = questionBank.essay_questions;
                    currentQuestion = generatedExam.questions.essay[questionIndex];
                    break;
                case 'calculation':
                    availableQuestions = questionBank.calculation_questions;
                    currentQuestion = generatedExam.questions.calculation[questionIndex];
                    break;
            }

            // 过滤掉当前已使用的题目ID，避免替换为相同的题目
            const currentQuestionId = currentQuestion.id;
            const otherQuestions = availableQuestions.filter(q => q.id !== currentQuestionId);

            if (otherQuestions.length === 0) {
                alert('没有其他可用的题目进行替换！');
                return;
            }

            // 随机选择一个新题目
            const newQuestion = otherQuestions[Math.floor(Math.random() * otherQuestions.length)];

            // 替换题目
            switch(questionCategory) {
                case 'single_choice':
                    generatedExam.questions.single_choice[questionIndex] = newQuestion;
                    break;
                case 'true_false':
                    generatedExam.questions.true_false[questionIndex] = newQuestion;
                    break;
                case 'essay':
                    generatedExam.questions.essay[questionIndex] = newQuestion;
                    break;
                case 'calculation':
                    generatedExam.questions.calculation[questionIndex] = newQuestion;
                    break;
            }

            // 更新预览
            displayExamPreview(generatedExam, currentPreviewMode);

            alert(`题目已替换为：${newQuestion.id}`);
        }

        // 导出试卷为Word格式
        function downloadExamAsWord() {
            if (!generatedExam) {
                alert('请先生成试卷！');
                return;
            }

            // 创建一个隐藏的iframe用于Word文档生成
            const iframe = document.createElement('iframe');
            iframe.style.display = 'none';
            document.body.appendChild(iframe);

            const doc = iframe.contentDocument || iframe.contentWindow.document;
            doc.open();
            doc.write(`
                <html>
                <head>
                    <meta charset="UTF-8">
                    <title>林业经济学试卷</title>
                    <style>
                        body { font-family: SimSun, serif; margin: 40px; }
                        .header { text-align: center; font-size: 18px; font-weight: bold; margin-bottom: 20px; }
                        .section { margin: 20px 0; }
                        .question { margin: 15px 0; }
                        .options { margin-left: 20px; }
                    </style>
                </head>
                <body>
                    <div class="header">${generatedExam.header.replace(/\n/g, '<br>')}</div>
            `);

            // 添加单选题
            if (generatedExam.questions.single_choice.length > 0) {
                doc.write(`<div class="section"><h3>一、单选题（每题${generatedExam.question_types.single_choice.score_per_question}分，共${generatedExam.questions.single_choice.length * generatedExam.question_types.single_choice.score_per_question}分）</h3>`);
                generatedExam.questions.single_choice.forEach((q, index) => {
                    const formattedQ = formatQuestionForWord(q, 'single_choice', index + 1, currentPreviewMode);
                    doc.write(`<div class="question">${formattedQ.replace(/\n/g, '<br>')}</div>`);
                });
                doc.write('</div>');
            }

            // 添加是非题
            if (generatedExam.questions.true_false.length > 0) {
                const score = generatedExam.question_types.true_false.score_per_question;
                const totalScore = generatedExam.questions.true_false.length * score;
                doc.write(`<div class="section"><h3>二、是非题（每题${score}分，共${totalScore}分）</h3>`);
                generatedExam.questions.true_false.forEach((q, index) => {
                    const formattedQ = formatQuestionForWord(q, 'true_false', index + 1, currentPreviewMode);
                    doc.write(`<div class="question">${formattedQ.replace(/\n/g, '<br>')}</div>`);
                });
                doc.write('</div>');
            }

            // 添加论述题
            if (generatedExam.questions.essay.length > 0) {
                const score = generatedExam.question_types.essay.score_per_question;
                const totalScore = generatedExam.questions.essay.length * score;
                doc.write(`<div class="section"><h3>三、论述题（每题${score}分，共${totalScore}分）</h3>`);
                generatedExam.questions.essay.forEach((q, index) => {
                    const formattedQ = formatQuestionForWord(q, 'essay', index + 1, currentPreviewMode);
                    doc.write(`<div class="question">${formattedQ.replace(/\n/g, '<br>')}</div>`);
                });
                doc.write('</div>');
            }

            // 添加计算题
            if (generatedExam.questions.calculation.length > 0) {
                const score = generatedExam.question_types.calculation.score_per_question;
                const totalScore = generatedExam.questions.calculation.length * score;
                doc.write(`<div class="section"><h3>四、计算题（每题${score}分，共${totalScore}分）</h3>`);
                generatedExam.questions.calculation.forEach((q, index) => {
                    const formattedQ = formatQuestionForWord(q, 'calculation', index + 1, currentPreviewMode);
                    doc.write(`<div class="question">${formattedQ.replace(/\n/g, '<br>')}</div>`);
                });
                doc.write('</div>');
            }

            doc.write('</body></html>');
            doc.close();

            // 触发Word文档下载
            setTimeout(() => {
                iframe.focus();
                iframe.contentWindow.print();
                document.body.removeChild(iframe);
            }, 500);
        }

        // 为Word格式化题目
        function formatQuestionForWord(question, qType, index, mode) {
            let result = `${index}. `;

            switch(qType) {
                case 'single_choice':
                    if (mode === 'chinese') {
                        result += `${question.chinese_stem}<br>`;
                        result += `A. ${question.options.A}<br>`;
                        result += `B. ${question.options.B}<br>`;
                        result += `C. ${question.options.C}<br>`;
                        result += `D. ${question.options.D}<br>`;
                        if (mode !== 'chinese_no_answer') {
                            result += `正确答案：${question.correct_answer}<br>`;
                        }
                    } else if (mode === 'english') {
                        result += `${question.english_stem}<br>`;
                        result += `A. ${question.options.A_en}<br>`;
                        result += `B. ${question.options.B_en}<br>`;
                        result += `C. ${question.options.C_en}<br>`;
                        result += `D. ${question.options.D_en}<br>`;
                        if (mode !== 'chinese_no_answer') {
                            result += `Correct Answer: ${question.correct_answer}<br>`;
                        }
                    } else if (mode === 'bilingual') {
                        result += `${question.chinese_stem}<br>`;
                        result += `${question.english_stem}<br>`;
                        result += `A. ${question.options.A} / ${question.options.A_en}<br>`;
                        result += `B. ${question.options.B} / ${question.options.B_en}<br>`;
                        result += `C. ${question.options.C} / ${question.options.C_en}<br>`;
                        result += `D. ${question.options.D} / ${question.options.D_en}<br>`;
                        if (mode !== 'chinese_no_answer') {
                            result += `正确答案：${question.correct_answer} / Correct Answer: ${question.correct_answer}<br>`;
                        }
                    } else if (mode === 'chinese_no_answer') {
                        result += `${question.chinese_stem}<br>`;
                        result += `A. ${question.options.A}<br>`;
                        result += `B. ${question.options.B}<br>`;
                        result += `C. ${question.options.C}<br>`;
                        result += `D. ${question.options.D}<br>`;
                    } else if (mode === 'bilingual_with_answer') {
                        result += `${question.chinese_stem}<br>`;
                        result += `${question.english_stem}<br>`;
                        result += `A. ${question.options.A} / ${question.options.A_en}<br>`;
                        result += `B. ${question.options.B} / ${question.options.B_en}<br>`;
                        result += `C. ${question.options.C} / ${question.options.C_en}<br>`;
                        result += `D. ${question.options.D} / ${question.options.D_en}<br>`;
                        result += `正确答案：${question.correct_answer} / Correct Answer: ${question.correct_answer}<br>`;
                        result += `解释：${question.explanation || ''} / Explanation: ${question.explanation_en || ''}<br>`;
                    }
                    break;

                case 'true_false':
                    if (mode === 'chinese') {
                        result += `${question.chinese_stem}<br>`;
                        if (mode !== 'chinese_no_answer') {
                            result += `答案：${question.correct_answer === 'T' ? '正确' : '错误'} (${question.correct_answer})<br>`;
                        }
                    } else if (mode === 'english') {
                        result += `${question.english_stem}<br>`;
                        if (mode !== 'chinese_no_answer') {
                            result += `Answer: ${question.correct_answer}<br>`;
                        }
                    } else if (mode === 'bilingual') {
                        result += `${question.chinese_stem}<br>`;
                        result += `${question.english_stem}<br>`;
                        if (mode !== 'chinese_no_answer') {
                            result += `答案：${question.correct_answer === 'T' ? '正确' : '错误'} / Answer: ${question.correct_answer}<br>`;
                        }
                    } else if (mode === 'chinese_no_answer') {
                        result += `${question.chinese_stem}<br>`;
                    } else if (mode === 'bilingual_with_answer') {
                        result += `${question.chinese_stem}<br>`;
                        result += `${question.english_stem}<br>`;
                        result += `答案：${question.correct_answer === 'T' ? '正确' : '错误'} / Answer: ${question.correct_answer}<br>`;
                        result += `解释：${question.explanation} / Explanation: ${question.explanation_en}<br>`;
                    }
                    break;

                case 'essay':
                    if (mode === 'chinese') {
                        result += `${question.chinese_stem}`;
                    } else if (mode === 'english') {
                        result += `${question.english_stem}`;
                    } else if (mode === 'bilingual') {
                        result += `${question.chinese_stem}<br>`;
                        result += `${question.english_stem}`;
                    } else if (mode === 'chinese_no_answer' || mode === 'bilingual_with_answer') {
                        result += `${question.chinese_stem}<br>`;
                        result += `${question.english_stem}`;
                        if (mode === 'bilingual_with_answer') {
                            result += `<br>评分标准：${question.scoring_guide.join('; ')} / Scoring Guide: ${question.scoring_guide_en.join('; ')}<br>`;
                        }
                    }
                    break;

                case 'calculation':
                    if (mode === 'chinese') {
                        result += `${question.context.chinese}`;
                        if (question.alternatives) {
                            question.alternatives.forEach((alt, i) => {
                                result += `<br>${i+1}. ${alt.description.chinese}`;
                            });
                        }
                        if (question.parameters) {
                            result += `<br>参数: ${JSON.stringify(question.parameters)}`;
                        }
                        question.requirements.chinese.forEach(req => {
                            result += `<br>要求: ${req}`;
                        });
                    } else if (mode === 'english') {
                        result += `${question.context.english}`;
                        if (question.alternatives) {
                            question.alternatives.forEach((alt, i) => {
                                result += `<br>${i+1}. ${alt.description.english}`;
                            });
                        }
                        if (question.parameters) {
                            result += `<br>Parameters: ${JSON.stringify(question.parameters)}`;
                        }
                        question.requirements.english.forEach(req => {
                            result += `<br>Requirements: ${req}`;
                        });
                    } else if (mode === 'bilingual') {
                        result += `${question.context.chinese}<br>`;
                        result += `${question.context.english}<br>`;
                        if (question.alternatives) {
                            question.alternatives.forEach((alt, i) => {
                                result += `${i+1}. ${alt.description.chinese} / ${alt.description.english}<br>`;
                            });
                        }
                        if (question.parameters) {
                            result += `参数: ${JSON.stringify(question.parameters)} / Parameters: ${JSON.stringify(question.parameters)}<br>`;
                        }
                        question.requirements.chinese.forEach((req, i) => {
                            result += `要求: ${req} / Requirements: ${question.requirements.english[i] || ''}<br>`;
                        });
                    } else if (mode === 'chinese_no_answer' || mode === 'bilingual_with_answer') {
                        result += `${question.context.chinese}<br>`;
                        result += `${question.context.english}<br>`;
                        if (question.alternatives) {
                            question.alternatives.forEach((alt, i) => {
                                result += `${i+1}. ${alt.description.chinese} / ${alt.description.english}<br>`;
                            });
                        }
                        if (question.parameters) {
                            result += `参数: ${JSON.stringify(question.parameters)} / Parameters: ${JSON.stringify(question.parameters)}<br>`;
                        }
                        question.requirements.chinese.forEach((req, i) => {
                            result += `要求: ${req} / Requirements: ${question.requirements.english[i] || ''}<br>`;
                        });
                    }
                    break;
            }

            return result;
        }
        
        // 下载试卷
        function downloadExam() {
            const examContent = document.getElementById('examContent').textContent;
            const blob = new Blob([examContent], { type: 'text/plain' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = '林业经济学试卷_' + document.getElementById('paperType').value + '.txt';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }
        
        // 下载Word模板
        function downloadTemplate(type) {
            fetch(`/api/download-template/${type}`)
                .then(response => response.blob())
                .then(blob => {
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `${type}_template.docx`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);
                })
                .catch(error => {
                    alert('下载模板失败: ' + error);
                });
        }
        
        // 实时计算总分
        function calculateTotalScore() {
            const scCount = parseInt(document.getElementById('scCount').value) || 0;
            const scScore = parseInt(document.getElementById('scScore').value) || 0;
            const tfCount = parseInt(document.getElementById('tfCount').value) || 0;
            const tfScore = parseInt(document.getElementById('tfScore').value) || 0;
            const esCount = parseInt(document.getElementById('esCount').value) || 0;
            const esScore = parseInt(document.getElementById('esScore').value) || 0;
            const calcCount = parseInt(document.getElementById('calcCount').value) || 0;
            const calcScore = parseInt(document.getElementById('calcScore').value) || 0;

            const totalScore = scCount * scScore + tfCount * tfScore + esCount * esScore + calcCount * calcScore;
            document.getElementById('totalScore').textContent = totalScore;

            return totalScore;
        }

        // 一键自动组卷
        function autoGenerateExam() {
            // 根据题库中题目数量智能生成试卷配置
            const totalSc = questionBank.single_choice_questions.length;
            const totalTf = questionBank.true_false_questions.length;
            const totalEs = questionBank.essay_questions.length;
            const totalCalc = questionBank.calculation_questions.length;

            // 设置默认值，如果题库中题目数量不足则相应减少
            const scCount = Math.min(totalSc, Math.max(5, Math.floor(Math.random() * 6) + 5)); // 5-10题，不超过题库数量
            const scScore = Math.floor(Math.random() * 4) + 1; // 1-4分
            const tfCount = Math.min(totalTf, Math.max(5, Math.floor(Math.random() * 6) + 5)); // 5-10题，不超过题库数量
            const tfScore = Math.floor(Math.random() * 4) + 1; // 1-4分
            const esCount = Math.min(totalEs, Math.max(1, Math.floor(Math.random() * 3) + 1)); // 1-3题，不超过题库数量
            const esScore = Math.floor(Math.random() * 11) + 10; // 10-20分
            const calcCount = Math.min(totalCalc, Math.max(1, Math.floor(Math.random() * 2) + 1)); // 1-2题，不超过题库数量
            const calcScore = Math.floor(Math.random() * 21) + 15; // 15-35分

            // 检查是否至少有一种题型有题目
            if (scCount === 0 && tfCount === 0 && esCount === 0 && calcCount === 0) {
                alert('题库中没有足够的题目生成试卷！');
                return;
            }

            // 更新表单值
            document.getElementById('scCount').value = scCount;
            document.getElementById('scScore').value = scScore;
            document.getElementById('tfCount').value = tfCount;
            document.getElementById('tfScore').value = tfScore;
            document.getElementById('esCount').value = esCount;
            document.getElementById('esScore').value = esScore;
            document.getElementById('calcCount').value = calcCount;
            document.getElementById('calcScore').value = calcScore;

            // 计算总分
            calculateTotalScore();

            // 生成试卷
            generateExam();
        }

        // 初始化页面
        window.onload = function() {
            refreshQuestionTable();
            // 初始化时计算总分
            calculateTotalScore();
        };
    </script>
</body>
</html>
    '''
    return render_template_string(html_content)

@app.route('/api/questions', methods=['GET'])
def get_questions():
    """获取所有题目"""
    return jsonify(question_bank)

@app.route('/api/questions', methods=['POST'])
def add_question():
    """添加新题目"""
    global question_bank
    question_data = request.json
    
    # 根据题型添加到对应的数组
    if question_data['type'] == 'single_choice':
        question_bank['single_choice_questions'].append(question_data)
    elif question_data['type'] == 'true_false':
        question_bank['true_false_questions'].append(question_data)
    elif question_data['type'] == 'essay':
        question_bank['essay_questions'].append(question_data)
    elif question_data['type'] == 'calculation':
        question_bank['calculation_questions'].append(question_data)
    
    return jsonify({"success": True, "message": "题目添加成功"})

@app.route('/api/questions/<question_type>/<int:index>', methods=['PUT'])
def update_question(question_type, index):
    """更新题目"""
    global question_bank
    question_data = request.json
    
    if question_type == 'single_choice':
        question_bank['single_choice_questions'][index] = question_data
    elif question_type == 'true_false':
        question_bank['true_false_questions'][index] = question_data
    elif question_type == 'essay':
        question_bank['essay_questions'][index] = question_data
    elif question_type == 'calculation':
        question_bank['calculation_questions'][index] = question_data
    
    return jsonify({"success": True, "message": "题目更新成功"})

@app.route('/api/questions/<question_type>/<int:index>', methods=['DELETE'])
def delete_question(question_type, index):
    """删除题目"""
    global question_bank
    
    if question_type == 'single_choice':
        if 0 <= index < len(question_bank['single_choice_questions']):
            question_bank['single_choice_questions'].pop(index)
    elif question_type == 'true_false':
        if 0 <= index < len(question_bank['true_false_questions']):
            question_bank['true_false_questions'].pop(index)
    elif question_type == 'essay':
        if 0 <= index < len(question_bank['essay_questions']):
            question_bank['essay_questions'].pop(index)
    elif question_type == 'calculation':
        if 0 <= index < len(question_bank['calculation_questions']):
            question_bank['calculation_questions'].pop(index)
    
    return jsonify({"success": True, "message": "题目删除成功"})

@app.route('/api/convert-word', methods=['POST'])
def convert_word():
    """转换Word文档为CSV"""
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "没有上传文件"})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "未选择文件"})
    
    if file and allowed_file(file.filename):
        # 保存上传的文件
        filename = secure_filename(file.filename)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp_file:
            file.save(tmp_file.name)
            temp_path = tmp_file.name
        
        try:
            # 创建转换器实例
            converter = WordToCsvConverter()

            # 从Word文档直接解析题目（不通过CSV中间步骤）
            questions = converter.parse_questions_from_word_doc(temp_path)

            if questions:
                # 将解析的题目添加到题库
                for question in questions:
                    qtype = question.get('type')
                    if qtype == 'single_choice':
                        # 确保选项格式正确
                        if 'options' not in question:
                            question['options'] = {"A": "", "A_en": "", "B": "", "B_en": "", "C": "", "C_en": "", "D": "", "D_en": ""}
                        question_bank['single_choice_questions'].append(question)
                    elif qtype == 'true_false':
                        question_bank['true_false_questions'].append(question)
                    elif qtype == 'essay':
                        question_bank['essay_questions'].append(question)
                    elif qtype == 'calculation':
                        question_bank['calculation_questions'].append(question)

                return jsonify({"success": True, "message": f"成功导入 {len(questions)} 道题目", "warnings": getattr(converter, 'warnings', [])})
            else:
                return jsonify({"success": False, "message": "未解析到任何题目"})
        
        except Exception as e:
            return jsonify({"success": False, "message": f"转换过程中发生错误: {str(e)}"})

        finally:
            # 清理临时文件
            try:
                os.unlink(temp_path)
                if os.path.exists(temp_path + '.csv'):
                    os.unlink(temp_path + '.csv')
            except:
                pass
    else:
        return jsonify({"success": False, "message": "仅支持.docx格式的文件"})

@app.route('/api/export/json', methods=['GET'])
def export_json():
    """导出题库为JSON"""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.json', mode='w', encoding='utf-8')
    json.dump(question_bank, temp_file, ensure_ascii=False, indent=2)
    temp_file.close()
    
    return send_file(temp_file.name, as_attachment=True, download_name='question_bank.json', 
                     mimetype='application/json')

@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    """导出题库为CSV"""
    import csv
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='w', encoding='utf-8-sig')
    
    writer = csv.writer(temp_file)
    
    # 写入单选题
    writer.writerow(['ID', 'Type', 'Difficulty', 'Chinese Stem', 'English Stem', 
                     'Option A (CH)', 'Option A (EN)', 'Option B (CH)', 'Option B (EN)',
                     'Option C (CH)', 'Option C (EN)', 'Option D (CH)', 'Option D (EN)',
                     'Correct Answer', 'Knowledge Point', 'Tags'])
    
    for q in question_bank['single_choice_questions']:
        writer.writerow([
            q['id'], 'single_choice', q['difficulty'], q['chinese_stem'], q['english_stem'],
            q['options']['A'], q['options']['A_en'], q['options']['B'], q['options']['B_en'],
            q['options']['C'], q['options']['C_en'], q['options']['D'], q['options']['D_en'],
            q['correct_answer'], q['knowledge_point'], ','.join(q['tags'])
        ])
    
    # 写入其他题型（简化处理）
    temp_file.close()
    
    return send_file(temp_file.name, as_attachment=True, download_name='question_bank.csv',
                     mimetype='text/csv')

@app.route('/api/generate-exam', methods=['POST'])
def generate_exam():
    """生成试卷"""
    config = request.json

    # 检查是否有手动选择的题目
    selected_questions = config.get('selected_questions', [])

    exam_content = f"""{config['school']}{config['academic_year']}期末考试试卷
课程名称：《{config['course_name']}（双语）》 （{config['paper_type']}）卷
课程代号：B0600432
考试形式：闭卷、笔试
使用对象：

题号	一	二	三	四	五	六	七	总分	总分人
分值
得分

 -------------------------------------------------------------------------------

得分    评阅人


"""

    # 按题型生成试卷
    question_types_map = {
        'single_choice': '单选题',
        'true_false': '是非题',
        'essay': '论述题',
        'calculation': '计算题'
    }

    # 生成各题型内容
    for qtype, qtype_name in question_types_map.items():
        q_config = config['question_types'][qtype]
        count = q_config['count']
        score_per_question = q_config['score_per_question']

        if count > 0:
            # 从手动选择的题目中筛选当前题型
            selected_of_type = [q for q in selected_questions if q['type'] == qtype]

            # 如果手动选择的题目数量不足，从题库中补充
            if len(selected_of_type) < count:
                remaining_count = count - len(selected_of_type)
                # 从题库中随机选择补充题目
                all_questions_of_type = question_bank[f"{qtype}_questions"]
                import random
                # 避免选择已手动选择的题目
                available_questions = [q for q in all_questions_of_type if q['id'] not in [sq['id'] for sq in selected_of_type]]
                additional_questions = random.sample(available_questions, min(remaining_count, len(available_questions)))
                all_questions_for_type = selected_of_type + additional_questions
            else:
                all_questions_for_type = selected_of_type[:count]

            exam_content += f"{qtype_name}：（共{len(all_questions_for_type)}题，每题{score_per_question}分，共{len(all_questions_for_type) * score_per_question}分）\n"

            if qtype == 'single_choice':
                exam_content += '请将答案统一填写在答题栏里\n'
                exam_content += '题号\t' + '\t'.join([str(i+1) for i in range(len(all_questions_for_type))]) + '\n'
                exam_content += '答案\t' + '\t'.join([' ' for _ in range(len(all_questions_for_type))]) + '\n\n'

            for i, q in enumerate(all_questions_for_type):
                q_data = q.get('data', q) if isinstance(q, dict) else q
                exam_content += f"{i+1}. {q_data.get('chinese_stem', '题目内容缺失')}\n"

                if qtype == 'single_choice':
                    exam_content += f"A. {q_data.get('options', {}).get('A', '')}\n"
                    exam_content += f"B. {q_data.get('options', {}).get('B', '')}\n"
                    exam_content += f"C. {q_data.get('options', {}).get('C', '')}\n"
                    exam_content += f"D. {q_data.get('options', {}).get('D', '')}\n\n"
                elif qtype == 'true_false':
                    exam_content += f"正确答案: {q_data.get('correct_answer', '')}\n\n"
                elif qtype == 'essay':
                    scoring_guide = q_data.get('scoring_guide', [])
                    exam_content += f"评分标准: {'; '.join(scoring_guide) if isinstance(scoring_guide, list) else str(scoring_guide)}\n\n"
                elif qtype == 'calculation':
                    context = q_data.get('context', {})
                    requirements = q_data.get('requirements', {})
                    exam_content += f"背景: {context.get('chinese', '')}\n"
                    req_chinese = requirements.get('chinese', [])
                    exam_content += f"要求: {'; '.join(req_chinese) if isinstance(req_chinese, list) else str(req_chinese)}\n\n"

    return jsonify({"exam_content": exam_content})

@app.route('/api/search-questions', methods=['POST'])
def search_questions():
    """搜索题目"""
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "message": "请求数据为空"}), 400

        keyword = data.get('keyword', '').lower()
        question_type = data.get('type', '')
        knowledge_point = data.get('knowledge_point', '')

        results = {
            "single_choice_questions": [],
            "true_false_questions": [],
            "essay_questions": [],
            "calculation_questions": []
        }

        # 搜索单选题
        for q in question_bank['single_choice_questions']:
            match = False
            if keyword and (keyword in q.get('chinese_stem', '').lower() or
                           keyword in q.get('english_stem', '').lower() or
                           keyword in q.get('knowledge_point', '').lower()):
                match = True
            elif not keyword:
                match = True

            if question_type and q.get('type') != question_type:
                match = False
            if knowledge_point and knowledge_point != q.get('knowledge_point', ''):
                match = False

            if match:
                results['single_choice_questions'].append(q)

        # 搜索是非题
        for q in question_bank['true_false_questions']:
            match = False
            if keyword and (keyword in q.get('chinese_stem', '').lower() or
                           keyword in q.get('english_stem', '').lower() or
                           keyword in q.get('knowledge_point', '').lower()):
                match = True
            elif not keyword:
                match = True

            if question_type and q.get('type') != question_type:
                match = False
            if knowledge_point and knowledge_point != q.get('knowledge_point', ''):
                match = False

            if match:
                results['true_false_questions'].append(q)

        # 搜索论述题
        for q in question_bank['essay_questions']:
            match = False
            if keyword and (keyword in q.get('chinese_stem', '').lower() or
                           keyword in q.get('english_stem', '').lower() or
                           keyword in q.get('knowledge_point', '').lower()):
                match = True
            elif not keyword:
                match = True

            if question_type and q.get('type') != question_type:
                match = False
            if knowledge_point and knowledge_point != q.get('knowledge_point', ''):
                match = False

            if match:
                results['essay_questions'].append(q)

        # 搜索计算题
        for q in question_bank['calculation_questions']:
            match = False
            if keyword and (keyword in q.get('context', {}).get('chinese', '').lower() or
                           keyword in q.get('context', {}).get('english', '').lower() or
                           keyword in q.get('knowledge_point', '').lower()):
                match = True
            elif not keyword:
                match = True

            if question_type and q.get('type') != question_type:
                match = False
            if knowledge_point and knowledge_point != q.get('knowledge_point', ''):
                match = False

            if match:
                results['calculation_questions'].append(q)

        return jsonify(results)
    except Exception as e:
        return jsonify({"success": False, "message": f"搜索题目时发生错误: {str(e)}"}), 500

@app.route('/api/save-exam', methods=['POST'])
def save_exam():
    """保存试卷组卷"""
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "message": "请求数据为空"}), 400

        exam_id = data.get('exam_id', f"exam_{int(datetime.now().timestamp())}")
        exam_data = data.get('exam_data', {})

        saved_exams[exam_id] = {
            'id': exam_id,
            'name': exam_data.get('name', f'试卷_{exam_id}'),
            'config': exam_data.get('config', {}),
            'questions': exam_data.get('questions', {}),
            'created_at': datetime.now().isoformat()
        }

        return jsonify({"success": True, "exam_id": exam_id, "message": "试卷保存成功"})
    except Exception as e:
        return jsonify({"success": False, "message": f"保存试卷时发生错误: {str(e)}"}), 500

@app.route('/api/load-exam/<exam_id>', methods=['GET'])
def load_exam(exam_id):
    """加载保存的试卷"""
    try:
        if exam_id in saved_exams:
            return jsonify(saved_exams[exam_id])
        else:
            return jsonify({"success": False, "message": "试卷不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": f"加载试卷时发生错误: {str(e)}"}), 500

@app.route('/api/list-saved-exams', methods=['GET'])
def list_saved_exams():
    """列出所有保存的试卷"""
    try:
        return jsonify(list(saved_exams.values()))
    except Exception as e:
        return jsonify({"success": False, "message": f"获取试卷列表时发生错误: {str(e)}"}), 500

@app.route('/api/delete-exam/<exam_id>', methods=['DELETE'])
def delete_exam(exam_id):
    """删除保存的试卷"""
    try:
        if exam_id in saved_exams:
            del saved_exams[exam_id]
            return jsonify({"success": True, "message": "试卷删除成功"})
        else:
            return jsonify({"success": False, "message": "试卷不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": f"删除试卷时发生错误: {str(e)}"}), 500

@app.route('/api/download-template/<template_type>', methods=['GET'])
def download_template(template_type):
    """下载Word模板"""
    if template_type not in ['single_choice', 'true_false', 'essay', 'calculation']:
        return jsonify({"success": False, "message": "无效的模板类型"}), 400

    # 创建转换器实例
    converter = WordToCsvConverter()

    # 创建临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp_file:
        converter.create_word_template(template_type, tmp_file.name)
        temp_path = tmp_file.name

    return send_file(temp_path, as_attachment=True,
                     download_name=f'{template_type}_template.docx',
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

if __name__ == '__main__':
    print("林业经济学（双语）试题管理系统")
    print("服务器启动中...")
    print("请在浏览器中打开 http://localhost:5000 访问系统")
    app.run(debug=True, host='0.0.0.0', port=5000)