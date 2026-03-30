# ServiceRequest — User Guide

## What is a ServiceRequest?

A ServiceRequest is a formal order for healthcare services. It combines:

- **A patient** — who the service is for
- **A service plan** (PlanDefinition) — what services are being requested
- **A contract match** — which provider(s) can deliver the service

Think of it as a structured order form: you pick a patient, choose what service they need, optionally customise the details, then send it to matching providers.

---

## Step-by-Step Guide

### 1. Create a ServiceRequest

1. Go to **ServiceRequests** in the navigation bar
2. Click **+ New ServiceRequest**
3. Select a **Patient** from the dropdown
4. Select a **PlanDefinition** (service plan) from the dropdown
5. Add optional **Notes**
6. Click **Create Draft**

The ServiceRequest is now in **draft** status. Nothing has been sent anywhere yet.

### 2. Review and Edit the Service Plan

While in draft, you can customise the PlanDefinition:

1. On the ServiceRequest detail page, click **Edit Snapshot**
2. Modify the JSON as needed (change activity details, requirements, etc.)
3. Click **Save Changes**

This only edits the local copy — the original PlanDefinition in Plan is not affected.

### 3. Finalize the ServiceRequest

When you're satisfied with the details:

1. Click **Finalize**
2. Confirm the action

This does two things:
- Builds a formal FHIR R5 ServiceRequest resource (visible in the "FHIR R5 Resource" section)
- Changes status from **draft** to **active**

Once finalized, the service plan can no longer be edited.

### 4. Find Contract Matches

With an active ServiceRequest, find providers who can deliver the service:

1. Click **Find Contract Matches**
2. The system checks all active contracts and shows matching providers
3. Matches appear in the **Contract Matches** table

### 5. Push to Providers

Send the ServiceRequest to matched providers:

1. Click **Push to Providers**
2. Confirm the action
3. Each matched provider receives the request
4. **Delivery Receipts** appear showing delivery status

Each receipt has a unique token that providers use to respond.

### 6. Provider Responses

Providers respond through their own systems using the receipt token. Their acceptance or rejection appears in the **Contract Matches** table with updated status:
- **pending** — not yet sent
- **sent** — delivered, awaiting response
- **accepted** — provider accepted
- **rejected** — provider declined

### 7. Archive or Revoke

- **Archive** — Mark as complete. Use when all data has been received or the service period has ended.
- **Revoke** — Cancel the request. Only possible if no provider has accepted.

ServiceRequests past their validity period are automatically archived.

---

## Status Lifecycle

```
draft → active → completed / archived / revoked
```

| Status | Meaning | What you can do |
|--------|---------|-----------------|
| Draft | Being prepared | Edit plan, finalize, archive, revoke |
| Active | Sent/ready for matching | Find matches, push, archive, revoke |
| Completed | All data received | View only |
| Archived | Expired or manually closed | View only |
| Revoked | Cancelled | View only |

---

## Who Can See What?

- **SU administrators** see all ServiceRequests across all organisations
- **Regular users** see only ServiceRequests from their own organisation

This is determined automatically by your login credentials.

---

## Where Does the Data Come From?

| Data | Source |
|------|--------|
| Patients | IPS (ips.pdhc.se) |
| Service Plans | Plan (plan.pdhc.se) |
| Contracts/Providers | Contract (contract.pdhc.se) |
| Authentication | SSO (sso.pdhc.se) |

When you create a ServiceRequest, the system fetches current data from these services and stores a snapshot locally. This means:
- The patient excerpt is frozen at creation time
- The PlanDefinition is a local copy that you can edit
- Changes to the original patient or plan do not affect existing ServiceRequests
