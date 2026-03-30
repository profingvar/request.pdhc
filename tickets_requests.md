1. when listing details about a request, give both guid and name of contractor and organisation

   DONE — Added `requester_user_name` and `requester_org_name` columns to ServiceRequest model (migration `c3d4e5f6a7b8`). Names are extracted from the SSO access blob (`display_name`, `organization_names`) at creation time and stored alongside GUIDs. The view.html details table now shows name + GUID (muted) for Requester, Organisation, and provider matches. The FHIR resource also carries display names in requester and organisation references.

2. For the period of development - In the request page I want a side by side with the json a creal text readout listing the objects (name, guid, weburl for lookup) in the blob that will be sent to the provider

   DONE — Replaced the old "FHIR R5 Resource" card with a two-column "Provider Delivery Blob (dev)" panel. Left column: Object Readout table listing every referenced resource (ServiceRequest, Patient, Requester, Organisation, PlanDefinition, Contract, Providers, CarePlan, Goals, Questionnaires) with display name, full GUID, and clickable lookup links to the relevant PDHC service (IPS, SSO, Plan, Contract). Right column: raw FHIR JSON with monospace styling.

3. When pressing create draft/finalaize I want a .json below the finalize/archive/revoke keys and side by side a readout from the json os the rendered questionnaire (All questions)

   DONE — Added a "Questionnaire Readout (dev)" card below the action buttons, shown once forms have snapshots (i.e. after finalization). For each attached form with a snapshot: left column renders a numbered table of all questions (text, type, required) with up to 3 levels of nesting; right column shows the raw Questionnaire JSON. Multiple forms are shown stacked with dividers.

4. add in the contract matches pane also the request GUID

   DONE — Added a "Request" column as the first column in the Contract Matches table, showing the full `service_request_guid` for each match.

5. Implement updates on request on miserver (now reachable ssh miserver). 

6. so the server is reached then ssh miserver@192.168.1.154 and repo is in /usr/local/www/request.pdhc
