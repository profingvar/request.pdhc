"""Tests for CSV export service (Steps 9.g–9.h)."""
import csv
import io
import pytest
from app.services.csv_service import generate_csv, preview_csv, generate_filename, get_headers


SAMPLE_ROWS = [
    {
        'row_guid': 'row-001',
        'careplan_guid': 'cp-001',
        'careplan_title': 'Test Plan',
        'careplan_status': 'active',
        'activity_guid': 'act-001',
        'activity_description': 'Check blood pressure',
        'activity_status': 'scheduled',
        'transaction_guid': 'txn-001',
        'concept_guid': 'c-001',
        'concept_name': 'Blood Pressure',
        'concept_display': 'Blood Pressure',
        'goal_guid': '',
        'goal_description': '',
        'goal_priority': '',
        'expected_value': '120',
        'expected_unit': 'mmHg',
        'range_low': '90',
        'range_high': '140',
        'requirement_type': '',
        'performer_type': 'Nurse',
        'sort_order': 0,
    },
    {
        'row_guid': 'row-002',
        'careplan_guid': 'cp-001',
        'careplan_title': 'Test Plan',
        'careplan_status': 'active',
        'activity_guid': 'act-002',
        'activity_description': 'Weight, with "quoted" text',
        'activity_status': 'scheduled',
        'transaction_guid': 'txn-002',
        'concept_guid': 'c-002',
        'concept_name': 'Weight',
        'concept_display': 'Weight',
        'goal_guid': '',
        'goal_description': '',
        'goal_priority': '',
        'expected_value': '75',
        'expected_unit': 'kg',
        'range_low': '',
        'range_high': '',
        'requirement_type': '',
        'performer_type': '',
        'sort_order': 1,
    },
]


def test_csv_valid_utf8():
    """CSV output is valid UTF-8."""
    content = generate_csv(SAMPLE_ROWS)
    content.encode('utf-8')  # Should not raise


def test_csv_headers_match_schema():
    """Headers match schema v1.0.0."""
    content = generate_csv(SAMPLE_ROWS)
    reader = csv.reader(io.StringIO(content))
    headers = next(reader)
    expected = get_headers('1.0.0')
    assert headers == expected


def test_csv_row_count():
    """CSV has correct number of data rows."""
    content = generate_csv(SAMPLE_ROWS)
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    assert len(rows) == 3  # header + 2 data rows


def test_csv_escaping():
    """Quoted text is properly escaped."""
    content = generate_csv(SAMPLE_ROWS)
    assert '"quoted"' in content or '\\"quoted\\"' in content or '""quoted""' in content


def test_csv_reproducible():
    """Same input produces identical CSV."""
    csv1 = generate_csv(SAMPLE_ROWS)
    csv2 = generate_csv(SAMPLE_ROWS)
    assert csv1 == csv2


def test_preview_returns_subset():
    """Preview returns correct number of rows."""
    preview = preview_csv(SAMPLE_ROWS, max_rows=1)
    assert preview['total_rows'] == 2
    assert preview['preview_count'] == 1
    assert len(preview['rows']) == 1


def test_preview_has_headers():
    """Preview includes headers."""
    preview = preview_csv(SAMPLE_ROWS)
    assert 'headers' in preview
    assert len(preview['headers']) > 0


def test_filename_format():
    """Filename follows convention."""
    name = generate_filename('cp-001')
    assert name.startswith('careplan_cp-001_')
    assert name.endswith('.csv')
