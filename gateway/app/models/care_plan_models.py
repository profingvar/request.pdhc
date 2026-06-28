"""CarePlan — patient-specific instance of a PlanDefinition.

Built per #310 (#294 RFC decision A1, 2026-06-28). Plan.pdhc owns the
template (PlanDefinition); request.pdhc creates a CarePlan FOR a
patient FROM a PlanDefinition. Observations reference a CarePlan via
basedOn[]; the chain
    Observation → CarePlan → PlanDefinition → Transaction → Concept
is the canonical provenance.

Historical note: the platform pre-#310 used "CarePlan" as a URL-level
misnomer for PlanDefinition (plan.pdhc only had PlanDefinition; a
proxy in request.pdhc forwarded `/api/v1/CarePlan` calls). The real
CarePlan layer lands here. The legacy proxy is being deprecated;
the new endpoint is `/api/v1/careplans` (lowercase) so the two
don't collide during transition.
"""
import uuid
from datetime import datetime, timezone
from app import db


class CarePlan(db.Model):
    """FHIR R5 CarePlan — patient-specific clinical plan instance.

    Derived from a PlanDefinition (the template) and tied to a
    Patient. Carries the per-patient overlay: status, period,
    individual goals, responsible care team. Each ServiceRequest
    issued against this CarePlan references it via
    ServiceRequest.care_plan_guid (added by the same migration).
    """
    __tablename__ = 'care_plans'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False,
                     default=lambda: str(uuid.uuid4()))

    # Patient + template references — both cross-service GUID strings;
    # PDHC convention is to keep cross-service references as strings,
    # not enforced FKs.
    patient_guid = db.Column(db.String(36), nullable=False, index=True)
    plan_definition_guid = db.Column(db.String(36), nullable=False,
                                     index=True)

    # FHIR R5 CarePlan.status: draft | active | on-hold | revoked |
    # completed | entered-in-error | unknown
    status = db.Column(db.String(20), nullable=False, default='draft')
    # FHIR R5 CarePlan.intent: proposal | plan | order | option
    intent = db.Column(db.String(20), nullable=False, default='plan')

    title = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # Active period for this care plan instance
    period_start = db.Column(db.DateTime(timezone=True), nullable=True)
    period_end = db.Column(db.DateTime(timezone=True), nullable=True)

    # Plan-definition snapshot — captured at create time so that later
    # edits to the template don't silently alter this patient's plan.
    # Same pattern as ServiceRequest.plan_definition_snapshot.
    plan_definition_snapshot = db.Column(db.JSON, nullable=True)

    # Goals overlay — JSON list of
    # {concept_guid, target_value, target_comparator, description}.
    # Inherits PlanDefinition.goals at create time; clinicians can
    # tighten thresholds for this specific patient by editing the
    # overlay.
    goals = db.Column(db.JSON, nullable=True)

    # Care team — list of user_guids responsible for this plan
    care_team_user_guids = db.Column(db.JSON, nullable=True)

    # Audit
    created_by_user_guid = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'guid': self.guid,
            'care_plan_guid': self.guid,  # canonical alias per #294
            'patient_guid': self.patient_guid,
            'plan_definition_guid': self.plan_definition_guid,
            'status': self.status,
            'intent': self.intent,
            'title': self.title,
            'description': self.description,
            'period_start': (self.period_start.isoformat()
                             if self.period_start else None),
            'period_end': (self.period_end.isoformat()
                           if self.period_end else None),
            'plan_definition_snapshot': self.plan_definition_snapshot,
            'goals': self.goals or [],
            'care_team_user_guids': self.care_team_user_guids or [],
            'created_by_user_guid': self.created_by_user_guid,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
