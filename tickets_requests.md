1. when listing details about a request, give both guid and name of contractor and organisation

   DONE — Added `requester_user_name` and `requester_org_name` columns to ServiceRequest model (migration `c3d4e5f6a7b8`). Names are extracted from the SSO access blob (`display_name`, `organization_names`) at creation time and stored alongside GUIDs. The view.html details table now shows name + GUID (muted) for Requester, Organisation, and provider matches. The FHIR resource also carries display names in requester and organisation references.

2. For the period of development - In the request page I want a side by side with the json a creal text readout listing the objects (name, guid, weburl for lookup) in the blob that will be sent to the provider

   DONE — Replaced the old "FHIR R5 Resource" card with a two-column "Provider Delivery Blob (dev)" panel. Left column: Object Readout table listing every referenced resource (ServiceRequest, Patient, Requester, Organisation, PlanDefinition, Contract, Providers, CarePlan, Goals, Questionnaires) with display name, full GUID, and clickable lookup links to the relevant PDHC service (IPS, SSO, Plan, Contract). Right column: raw FHIR JSON with monospace styling.

3. When pressing create draft/finalaize I want a .json below the finalize/archive/revoke keys and side by side a readout from the json os the rendered questionnaire (All questions)

   DONE — Added a "Questionnaire Readout (dev)" card below the action buttons, shown once forms have snapshots (i.e. after finalization). For each attached form with a snapshot: left column renders a numbered table of all questions (text, type, required) with up to 3 levels of nesting; right column shows the raw Questionnaire JSON. Multiple forms are shown stacked with dividers.

4. add in the contract matches pane also the request GUID

   DONE — Added a "Request" column as the first column in the Contract Matches table, showing the full `service_request_guid` for each match.

5. Implement updates on request on miserver (now reachable ssh miserver).

   DONE — Committed all changes (10b98b6), pushed to origin/main, pulled on miserver. Stale local files on server were cleaned. Docker image rebuilt, containers restarted, migration c3d4e5f6a7b8 applied automatically. Health check passing: `{"database":"connected","status":"ok"}`.

6. so the server is reached then ssh miserver@192.168.1.154 and repo is in /usr/local/www/request.pdhc

   DONE — Server access confirmed: `ssh miserver@192.168.1.154`, repo at `/usr/local/www/request.pdhc`. Docker via Homebrew (`/opt/homebrew/bin/docker-compose`). Deploy command: `export PATH=/opt/homebrew/bin:$PATH && cd /usr/local/www/request.pdhc/gateway && docker-compose down && docker-compose up -d --build`.

7. Item in request ska med på listan Provider Delivery Blob (dev). Conceptet QOL är en slider inte som det står integer. Likaså skilj på enval och flervalsfrgåor inför rendering.

   DONE — Three changes in view.html: (1) Questionnaire items now listed under each Questionnaire row in the Provider Delivery Blob readout, showing text, render type, and linkId with nested indentation. (2) Added a `render_type` Jinja macro that detects the `questionnaire-itemControl` extension with code `slider` on `integer` items and displays "slider" instead of "integer". (3) `choice` items are now shown as "single-choice" or "multi-choice" (based on `repeats`), and `open-choice` likewise. The same macro is used in both the Questionnaire Readout and the Provider Delivery Blob panels.
