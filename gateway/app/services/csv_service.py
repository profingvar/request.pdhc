import csv
import io
from datetime import datetime, timezone

# CSV schema v1.0.0 — stable header order
CSV_HEADERS_V1 = [
    'row_guid',
    'careplan_guid',
    'careplan_title',
    'careplan_status',
    'activity_guid',
    'activity_description',
    'activity_status',
    'transaction_guid',
    'concept_guid',
    'concept_name',
    'concept_display',
    'goal_guid',
    'goal_description',
    'goal_priority',
    'expected_value',
    'expected_unit',
    'range_low',
    'range_high',
    'requirement_type',
    'performer_type',
    'sort_order',
]


def get_headers(schema_version='1.0.0'):
    """Return headers for the given schema version."""
    if schema_version == '1.0.0':
        return CSV_HEADERS_V1
    return CSV_HEADERS_V1


def generate_csv(transaction_rows, schema_version='1.0.0'):
    """Generate UTF-8 CSV content from normalized transaction rows.

    Returns:
        str: CSV content as string.
    """
    output = io.StringIO()
    headers = get_headers(schema_version)
    writer = csv.DictWriter(output, fieldnames=headers, quoting=csv.QUOTE_ALL, extrasaction='ignore')
    writer.writeheader()
    for row in transaction_rows:
        writer.writerow(row)
    return output.getvalue()


def preview_csv(transaction_rows, max_rows=20):
    """Return preview data: headers and first N rows.

    Returns:
        dict: {'headers': [...], 'rows': [...], 'total_rows': int}
    """
    headers = get_headers('1.0.0')
    preview_rows = transaction_rows[:max_rows]
    return {
        'headers': headers,
        'rows': preview_rows,
        'total_rows': len(transaction_rows),
        'preview_count': len(preview_rows),
    }


def generate_filename(careplan_guid):
    """Generate deterministic CSV filename."""
    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return f"careplan_{careplan_guid}_{ts}.csv"
