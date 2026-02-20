"""Tests for the course settings API."""
import json
import pytest


class TestGetCourseSettings:
    """Tests for GET /api/course-settings."""

    def test_get_default_settings(self, client):
        """First GET auto-creates default empty settings."""
        response = client.get('/api/course-settings')
        assert response.status_code == 200
        data = response.get_json()
        assert data['course_name'] == ''
        assert data['course_code'] == ''
        assert data['exam_format'] == ''
        assert data['exam_method'] == ''
        assert data['target_audience'] == ''
        assert data['institution_name'] == ''
        assert data['semester_info'] == ''
        assert data['exam_title'] == '期末考试试卷'
        assert data['paper_label'] == 'A'
        assert 'id' in data
        assert 'updated_at' in data

    def test_get_returns_same_record(self, client):
        """Multiple GETs return the same single record."""
        r1 = client.get('/api/course-settings')
        r2 = client.get('/api/course-settings')
        assert r1.get_json()['id'] == r2.get_json()['id']


class TestUpdateCourseSettings:
    """Tests for PUT /api/course-settings."""

    def test_update_all_fields(self, client):
        """Update all course settings fields."""
        data = {
            'course_name': '林业经济学（双语）',
            'course_code': 'FE301',
            'exam_format': '闭卷',
            'exam_method': '笔试',
            'target_audience': '林学专业本科生',
            'institution_name': '中南财经政法大学',
            'semester_info': '2023–2024学年第1学期',
            'exam_title': '期末考试试卷',
            'paper_label': 'A',
        }
        response = client.put('/api/course-settings',
                              data=json.dumps(data),
                              content_type='application/json')
        assert response.status_code == 200
        result = response.get_json()
        assert result['course_name'] == '林业经济学（双语）'
        assert result['course_code'] == 'FE301'
        assert result['exam_format'] == '闭卷'
        assert result['exam_method'] == '笔试'
        assert result['target_audience'] == '林学专业本科生'
        assert result['institution_name'] == '中南财经政法大学'
        assert result['semester_info'] == '2023–2024学年第1学期'
        assert result['exam_title'] == '期末考试试卷'
        assert result['paper_label'] == 'A'

    def test_update_partial_fields(self, client):
        """Updating only some fields leaves others unchanged."""
        # First set all fields
        client.put('/api/course-settings',
                   data=json.dumps({'course_name': 'Test Course', 'course_code': 'TC100'}),
                   content_type='application/json')

        # Update only course_name
        response = client.put('/api/course-settings',
                              data=json.dumps({'course_name': 'New Name'}),
                              content_type='application/json')
        result = response.get_json()
        assert result['course_name'] == 'New Name'
        assert result['course_code'] == 'TC100'  # unchanged

    def test_update_persists(self, client):
        """Settings persist after update."""
        client.put('/api/course-settings',
                   data=json.dumps({'course_name': 'Persisted Course'}),
                   content_type='application/json')

        response = client.get('/api/course-settings')
        assert response.get_json()['course_name'] == 'Persisted Course'

    def test_update_empty_values(self, client):
        """Can clear fields by setting to empty string."""
        client.put('/api/course-settings',
                   data=json.dumps({'course_name': 'Some Course'}),
                   content_type='application/json')

        response = client.put('/api/course-settings',
                              data=json.dumps({'course_name': ''}),
                              content_type='application/json')
        assert response.get_json()['course_name'] == ''

    def test_update_creates_if_not_exists(self, client):
        """PUT auto-creates settings row if none exists."""
        response = client.put('/api/course-settings',
                              data=json.dumps({'course_name': 'Auto Created'}),
                              content_type='application/json')
        assert response.status_code == 200
        assert response.get_json()['course_name'] == 'Auto Created'

    def test_update_new_header_fields(self, client):
        """Update institution_name, semester_info, exam_title, paper_label."""
        data = {
            'institution_name': '北京大学',
            'semester_info': '2024–2025学年第2学期',
            'exam_title': '期中考试试卷',
            'paper_label': 'B',
        }
        response = client.put('/api/course-settings',
                              data=json.dumps(data),
                              content_type='application/json')
        assert response.status_code == 200
        result = response.get_json()
        assert result['institution_name'] == '北京大学'
        assert result['semester_info'] == '2024–2025学年第2学期'
        assert result['exam_title'] == '期中考试试卷'
        assert result['paper_label'] == 'B'

    def test_partial_update_preserves_new_fields(self, client):
        """Updating old fields does not overwrite new header fields."""
        client.put('/api/course-settings',
                   data=json.dumps({'institution_name': '清华大学', 'paper_label': 'C'}),
                   content_type='application/json')
        response = client.put('/api/course-settings',
                              data=json.dumps({'course_name': 'Updated Course'}),
                              content_type='application/json')
        result = response.get_json()
        assert result['institution_name'] == '清华大学'
        assert result['paper_label'] == 'C'
        assert result['course_name'] == 'Updated Course'


class TestCourseSettingsModel:
    """Tests for CourseSettingsModel."""

    def test_model_to_dict(self, app, db):
        """CourseSettingsModel.to_dict returns all fields."""
        from app.db_models import CourseSettingsModel
        from datetime import datetime

        settings = CourseSettingsModel(
            course_name='Test',
            course_code='T01',
            exam_format='开卷',
            exam_method='口试',
            target_audience='测试对象',
            institution_name='测试大学',
            semester_info='2024学年',
            exam_title='期末考试试卷',
            paper_label='A',
            updated_at=datetime.now(),
        )
        db.session.add(settings)
        db.session.commit()

        d = settings.to_dict()
        assert d['course_name'] == 'Test'
        assert d['course_code'] == 'T01'
        assert d['exam_format'] == '开卷'
        assert d['exam_method'] == '口试'
        assert d['target_audience'] == '测试对象'
        assert d['institution_name'] == '测试大学'
        assert d['semester_info'] == '2024学年'
        assert d['exam_title'] == '期末考试试卷'
        assert d['paper_label'] == 'A'
        assert d['updated_at'] is not None

    def test_model_defaults(self, app, db):
        """CourseSettingsModel has correct defaults for new fields."""
        from app.db_models import CourseSettingsModel
        from datetime import datetime

        settings = CourseSettingsModel(updated_at=datetime.now())
        db.session.add(settings)
        db.session.commit()

        d = settings.to_dict()
        assert d['institution_name'] == ''
        assert d['semester_info'] == ''
        assert d['exam_title'] == '期末考试试卷'
        assert d['paper_label'] == 'A'
