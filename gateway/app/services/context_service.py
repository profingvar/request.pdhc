"""SR context extraction for gateway.pdhc internal API."""
from app.models.service_request_models import ServiceRequest


def get_sr_context(sr_guid):
    """Extract gateway-relevant context from a stored ServiceRequest.

    Returns a dict with pre-extracted transactions, goals, and metadata,
    or None if the SR doesn't exist.
    """
    sr = ServiceRequest.query.filter_by(guid=sr_guid).first()
    if not sr:
        return None

    fhir = sr.fhir_resource or {}
    transactions = _extract_transactions(fhir)
    goals = _extract_goals(fhir)

    return {
        'service_request_guid': sr.guid,
        'status': sr.status,
        'patient_guid': sr.patient_guid,
        'contract_guid': sr.contract_guid,
        'requester_org_guid': sr.requester_org_guid,
        'requester_user_guid': sr.requester_user_guid,
        'requester_user_name': sr.requester_user_name,
        'plan_definition_guid': sr.plan_definition_guid,
        'period_start': sr.period_start.isoformat() if sr.period_start else None,
        'period_end': sr.period_end.isoformat() if sr.period_end else None,
        'transactions': transactions,
        'goals': goals,
    }


def _extract_transactions(fhir_resource):
    """Extract transaction list from contained CarePlan._pdhc_transactions."""
    contained = fhir_resource.get('contained', [])
    for resource in contained:
        if resource.get('resourceType') != 'CarePlan':
            continue
        transactions = []
        for tx in resource.get('_pdhc_transactions', []):
            transactions.append({
                'transaction_guid': tx.get('transaction_guid'),
                'concept_guid': tx.get('concept_guid'),
                'concept_name': tx.get('concept_name', ''),
                'unit': tx.get('unit'),
                'unit_display': tx.get('unit_display', ''),
                'expected_value': tx.get('expected_value'),
                'range_min': tx.get('range_min'),
                'range_max': tx.get('range_max'),
                'requirement_type': tx.get('requirement_type', 'required'),
            })
        return transactions
    return []


def _extract_goals(fhir_resource):
    """Extract goals from contained Goal resources."""
    contained = fhir_resource.get('contained', [])
    goals = []
    for resource in contained:
        if resource.get('resourceType') != 'Goal':
            continue
        target = (resource.get('target') or [{}])[0] if resource.get('target') else {}
        concept_coding = (resource.get('description', {}).get('coding') or [{}])[0]
        goals.append({
            'description': resource.get('description', {}).get('text', ''),
            'concept_guid': concept_coding.get('code', ''),
            'priority': resource.get('priority', {}).get('text', ''),
            'target_value': target.get('detailQuantity', {}).get('value') if target else None,
            'target_comparator': target.get('detailQuantity', {}).get('comparator') if target else None,
        })
    return goals
