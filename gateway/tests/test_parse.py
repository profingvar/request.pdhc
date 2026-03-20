"""Tests for CarePlan parse/normalization service (Steps 8.b–8.c)."""
import pytest
from app.services.parse_service import parse_careplan


SAMPLE_CAREPLAN = {
    'resourceType': 'CarePlan',
    'id': 'test-careplan-001',
    'title': 'Test CarePlan',
    'status': 'active',
    'goal': [],
    'activity': [
        {
            'id': 'act-1',
            'detail': {
                'description': 'Blood pressure measurement',
                'status': 'scheduled',
                'code': {
                    'coding': [{'code': 'concept-bp-001', 'display': 'Blood Pressure'}]
                },
                'performer': [{'display': 'Nurse'}],
                'quantity': {'value': 120, 'unit': 'mmHg'},
            },
        },
        {
            'id': 'act-2',
            'detail': {
                'description': 'Weight check',
                'status': 'scheduled',
                'code': {
                    'coding': [{'code': 'concept-wt-001', 'display': 'Weight'}]
                },
            },
        },
    ],
}


def test_parse_produces_rows():
    """Parse produces expected number of rows."""
    rows, errors = parse_careplan(SAMPLE_CAREPLAN)
    assert len(rows) == 2
    assert len(errors) == 0


def test_parse_idempotent():
    """Same input always produces identical output."""
    rows1, _ = parse_careplan(SAMPLE_CAREPLAN)
    rows2, _ = parse_careplan(SAMPLE_CAREPLAN)
    assert rows1 == rows2


def test_parse_row_fields():
    """Each row has required fields."""
    rows, _ = parse_careplan(SAMPLE_CAREPLAN)
    required_fields = [
        'row_guid', 'careplan_guid', 'activity_guid', 'transaction_guid',
        'concept_guid', 'concept_name', 'sort_order',
    ]
    for row in rows:
        for field in required_fields:
            assert field in row, f"Missing field: {field}"


def test_parse_sort_order():
    """Sort order is preserved."""
    rows, _ = parse_careplan(SAMPLE_CAREPLAN)
    for i, row in enumerate(rows):
        assert row['sort_order'] == i


def test_parse_concept_data():
    """Concept data is extracted correctly."""
    rows, _ = parse_careplan(SAMPLE_CAREPLAN)
    assert rows[0]['concept_name'] == 'Blood Pressure'
    assert rows[0]['concept_guid'] == 'concept-bp-001'


def test_parse_expected_value():
    """Expected value is extracted."""
    rows, _ = parse_careplan(SAMPLE_CAREPLAN)
    assert rows[0]['expected_value'] == '120'
    assert rows[0]['expected_unit'] == 'mmHg'


def test_parse_performer():
    """Performer type is extracted."""
    rows, _ = parse_careplan(SAMPLE_CAREPLAN)
    assert rows[0]['performer_type'] == 'Nurse'


def test_parse_empty_careplan():
    """Empty input returns empty rows with error."""
    rows, errors = parse_careplan({})
    assert len(rows) == 0


def test_parse_none_input():
    """None input returns empty rows with error."""
    rows, errors = parse_careplan(None)
    assert len(rows) == 0
    assert len(errors) > 0


def test_parse_missing_optional_fields():
    """Missing optional fields use defaults, not errors."""
    minimal = {
        'resourceType': 'CarePlan',
        'id': 'minimal-001',
        'activity': [{'detail': {}}],
    }
    rows, errors = parse_careplan(minimal)
    assert len(rows) == 1
    assert rows[0]['concept_name'] == ''
    assert rows[0]['expected_value'] == ''
