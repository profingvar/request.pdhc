import uuid
from datetime import datetime, timezone
from app import db


class ServiceRequest(db.Model):
    """FHIR R5 ServiceRequest — patient excerpt + edited PlanDefinition snapshot."""
    __tablename__ = 'service_requests'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    status = db.Column(db.String(30), nullable=False, default='draft')
    intent = db.Column(db.String(20), nullable=False, default='order')
    priority = db.Column(db.String(20), nullable=False, default='routine')

    # Patient (from IPS)
    patient_guid = db.Column(db.String(36), nullable=False, index=True)
    patient_excerpt = db.Column(db.JSON, nullable=True)

    # PlanDefinition (from Plan)
    plan_definition_guid = db.Column(db.String(36), nullable=False)
    plan_definition_snapshot = db.Column(db.JSON, nullable=True)

    # CarePlan (the patient-specific instance, since #310). Optional —
    # SRs issued directly against a PlanDefinition leave it NULL
    # (legacy / direct workflow). When set, the chain
    # SR → CarePlan → PlanDefinition gives full provenance.
    care_plan_guid = db.Column(db.String(36), nullable=True, index=True)

    # Assembled FHIR R5 ServiceRequest resource
    fhir_resource = db.Column(db.JSON, nullable=True)

    # Contract reference
    contract_guid = db.Column(db.String(36), nullable=True, index=True)

    # Requester
    requester_user_guid = db.Column(db.String(36), nullable=False)
    requester_user_name = db.Column(db.String(255), nullable=True)
    requester_org_guid = db.Column(db.String(36), nullable=True, index=True)
    requester_org_name = db.Column(db.String(255), nullable=True)

    notes = db.Column(db.Text, nullable=True)

    # Validity period
    period_start = db.Column(db.DateTime, nullable=True)
    period_end = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    contract_matches = db.relationship('ServiceRequestContractMatch', backref='service_request', lazy=True)
    forms = db.relationship('ServiceRequestForm', backref='service_request', lazy=True,
                            order_by='ServiceRequestForm.sort_order')

    def to_dict(self):
        return {
            'guid': self.guid,
            'status': self.status,
            'intent': self.intent,
            'priority': self.priority,
            'patient_guid': self.patient_guid,
            'patient_excerpt': self.patient_excerpt,
            'plan_definition_guid': self.plan_definition_guid,
            'plan_definition_snapshot': self.plan_definition_snapshot,
            'fhir_resource': self.fhir_resource,
            'contract_guid': self.contract_guid,
            'requester_user_guid': self.requester_user_guid,
            'requester_user_name': self.requester_user_name,
            'requester_org_guid': self.requester_org_guid,
            'requester_org_name': self.requester_org_name,
            # #294 / #306 phase 6: canonical clinical-context names.
            # Emitted alongside the legacy `requester_*` keys during
            # the deprecation window; consumers should switch to
            # these. Legacy keys removed after one release cycle.
            'requesting_org_guid': self.requester_org_guid,
            'requesting_org_name': self.requester_org_name,
            'notes': self.notes,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'forms': [f.to_dict() for f in self.forms],
        }


class ServiceRequestForm(db.Model):
    """Links a ServiceRequest to one or more forms from the Plan catalogue."""
    __tablename__ = 'service_request_forms'
    __table_args__ = (
        db.UniqueConstraint('service_request_guid', 'form_guid', name='uq_sr_form'),
    )

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    service_request_guid = db.Column(db.String(36), db.ForeignKey('service_requests.guid'), nullable=False)
    form_guid = db.Column(db.String(36), nullable=False)
    form_version = db.Column(db.String(50), nullable=True)
    form_snapshot = db.Column(db.JSON, nullable=True)
    render_ready_snapshot = db.Column(db.JSON, nullable=True)
    display_title = db.Column(db.String(255), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'guid': self.guid,
            'service_request_guid': self.service_request_guid,
            'form_guid': self.form_guid,
            'form_version': self.form_version,
            'form_snapshot': self.form_snapshot,
            'render_ready_snapshot': self.render_ready_snapshot,
            'display_title': self.display_title,
            'sort_order': self.sort_order,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class ServiceRequestContractMatch(db.Model):
    """Links a ServiceRequest to a matching contract/provider."""
    __tablename__ = 'service_request_contract_matches'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    service_request_guid = db.Column(db.String(36), db.ForeignKey('service_requests.guid'), nullable=False)
    contract_guid = db.Column(db.String(36), nullable=False)
    provider_org_guid = db.Column(db.String(36), nullable=False, index=True)
    provider_name = db.Column(db.String(255), nullable=True)
    match_type = db.Column(db.String(20), nullable=False, default='offer')  # offer | push
    status = db.Column(db.String(30), nullable=False, default='pending')
    sent_at = db.Column(db.DateTime, nullable=True)
    response_at = db.Column(db.DateTime, nullable=True)
    response_payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    receipts = db.relationship('ServiceRequestReceipt', backref='contract_match', lazy=True)

    def to_dict(self):
        return {
            'guid': self.guid,
            'service_request_guid': self.service_request_guid,
            'contract_guid': self.contract_guid,
            'provider_org_guid': self.provider_org_guid,
            'provider_name': self.provider_name,
            'match_type': self.match_type,
            'status': self.status,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'response_at': self.response_at.isoformat() if self.response_at else None,
            'response_payload': self.response_payload,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class ServiceRequestReceipt(db.Model):
    """Delivery receipt for a pushed ServiceRequest."""
    __tablename__ = 'service_request_receipts'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    service_request_guid = db.Column(db.String(36), db.ForeignKey('service_requests.guid'), nullable=False)
    contract_match_guid = db.Column(db.String(36), db.ForeignKey('service_request_contract_matches.guid'), nullable=False)
    receipt_token = db.Column(db.String(255), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    delivery_method = db.Column(db.String(20), nullable=False, default='push')
    delivery_status = db.Column(db.String(30), nullable=False, default='pending')
    delivery_payload = db.Column(db.JSON, nullable=True)
    response_received = db.Column(db.Boolean, default=False)
    response_payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'guid': self.guid,
            'service_request_guid': self.service_request_guid,
            'contract_match_guid': self.contract_match_guid,
            'receipt_token': self.receipt_token,
            'delivery_method': self.delivery_method,
            'delivery_status': self.delivery_status,
            'response_received': self.response_received,
            'created_at': self.created_at.isoformat(),
        }
