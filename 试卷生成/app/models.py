import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
import uuid


class Question:
    """
    Question data structure supporting multiple question types:
    - Single choice
    - True/False
    - Essay
    - Calculation
    - Material-based
    """
    
    def __init__(self, question_id: str, question_type: str, content: str, 
                 options: Optional[List[str]] = None, answer: Optional[str] = None,
                 reference_answer: Optional[str] = None, explanation: Optional[str] = None,
                 language: str = "zh", metadata: Optional[Dict] = None):
        self.question_id = question_id
        self.question_type = question_type
        self.content = content
        self.options = options or []
        self.answer = answer
        self.reference_answer = reference_answer
        self.explanation = explanation
        self.language = language  # 'zh', 'en', or 'both'
        self.metadata = metadata or {}
        self.is_used = False  # Flag to track if question has been used in an exam
        self.used_date = None  # Date when question was used
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert question to dictionary for JSON serialization"""
        return {
            'question_id': self.question_id,
            'question_type': self.question_type,
            'content': self.content,
            'options': self.options,
            'answer': self.answer,
            'reference_answer': self.reference_answer,
            'explanation': self.explanation,
            'language': self.language,
            'metadata': self.metadata,
            'is_used': self.is_used,
            'used_date': self.used_date.isoformat() if self.used_date else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """Create question from dictionary"""
        question = cls(
            question_id=data.get('question_id', str(uuid.uuid4())),
            question_type=data.get('question_type', ''),
            content=data.get('content', ''),
            options=data.get('options'),
            answer=data.get('answer'),
            reference_answer=data.get('reference_answer'),
            explanation=data.get('explanation'),
            language=data.get('language', 'zh'),
            metadata=data.get('metadata')
        )
        if data.get('is_used'):
            question.is_used = True
            if data.get('used_date'):
                question.used_date = datetime.fromisoformat(data['used_date'])
        if data.get('created_at'):
            question.created_at = datetime.fromisoformat(data['created_at'])
        if data.get('updated_at'):
            question.updated_at = datetime.fromisoformat(data['updated_at'])
        
        return question
    
    def update_content(self, content: str, options: Optional[List[str]] = None, 
                      answer: Optional[str] = None, reference_answer: Optional[str] = None,
                      explanation: Optional[str] = None):
        """Update question content"""
        self.content = content
        if options is not None:
            self.options = options
        if answer is not None:
            self.answer = answer
        if reference_answer is not None:
            self.reference_answer = reference_answer
        if explanation is not None:
            self.explanation = explanation
        self.updated_at = datetime.now()


class Exam:
    """Exam class to manage exam-related data"""
    
    def __init__(self, exam_id: str, name: str, questions: Optional[List[Question]] = None,
                 config: Optional[Dict] = None, created_at: Optional[datetime] = None):
        self.exam_id = exam_id
        self.name = name
        self.questions = questions or []
        self.config = config or {}  # Configuration for the exam (points, types, etc.)
        self.created_at = created_at or datetime.now()
        self.updated_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exam to dictionary for JSON serialization"""
        return {
            'exam_id': self.exam_id,
            'name': self.name,
            'questions': [q.to_dict() for q in self.questions],
            'config': self.config,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """Create exam from dictionary"""
        questions = [Question.from_dict(q) for q in data.get('questions', [])]
        exam = cls(
            exam_id=data.get('exam_id', str(uuid.uuid4())),
            name=data.get('name', ''),
            questions=questions,
            config=data.get('config', {}),
        )
        if data.get('created_at'):
            exam.created_at = datetime.fromisoformat(data['created_at'])
        if data.get('updated_at'):
            exam.updated_at = datetime.fromisoformat(data['updated_at'])
        
        return exam
    
    def add_question(self, question: Question):
        """Add a question to the exam"""
        self.questions.append(question)
        self.updated_at = datetime.now()
    
    def remove_question(self, question_id: str):
        """Remove a question from the exam by ID"""
        self.questions = [q for q in self.questions if q.question_id != question_id]
        self.updated_at = datetime.now()
    
    def calculate_total_score(self) -> int:
        """Calculate the total score of the exam based on config"""
        total_score = 0
        if self.config:
            for question in self.questions:
                # Look up the score for this question type in the config
                question_config = self.config.get(question.question_type, {})
                points_per_question = question_config.get('points', 0)
                total_score += points_per_question
        return total_score
    
    def get_questions_by_type(self, question_type: str) -> List[Question]:
        """Get all questions of a specific type"""
        return [q for q in self.questions if q.question_type == question_type]


