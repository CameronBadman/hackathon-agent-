# Hackathon Calendar System (GCP + Terraform)

This repository provisions and deploys a full GCP system that:

- Discovers upcoming hackathons weekly using Gemini Flash + search grounding
- Filters events using a bundled `SKILLS.md` file at runtime
- Creates all-day invite events in a dedicated `Prospective Hackathons` calendar
- Tracks dedup and lifecycle state in Firestore (`pending`, `committed`, `declined`, `filtered`)
- Listens to Google Calendar push notifications
- Copies accepted events to a dedicated `Committed Hackathons` calendar
- Automatically renews expiring Calendar watch channels

## Project Layout

```text
/
  terraform/
    main.tf
    variables.tf
    outputs.tf
    terraform.tfvars.example
  functions/
    agent/
      main.py
      requirements.txt
      SKILLS.md
    webhook/
      main.py
      requirements.txt
  README.md
```

## Architecture Summary

1. `Cloud Scheduler` publishes weekly to a `Pub/Sub` topic.
2. `Cloud Function (Gen 2) - agent` is Pub/Sub-triggered.
3. Agent reads `SKILLS.md`, runs two Gemini steps:
   - Discovery with search grounding across major hackathon sources
   - Per-event validation against fetched page content + `SKILLS.md`
4. Agent dedups by normalized URL in Firestore:
   - Existing URL: skip
   - New non-match: store `filtered`
   - New match: create all-day event in `Prospective Hackathons`, store `pending`
5. `Cloud Function (Gen 2) - webhook` receives Calendar push notifications.
6. Webhook incremental-syncs event changes using sync token:
   - RSVP `accepted`: copy event to `Committed Hackathons`, set `committed`
   - RSVP `declined`: set `declined`
7. A second `Cloud Scheduler` job calls webhook `?action=renew` every 6 days to renew push channel before expiry.

## Prerequisites

- Terraform `>= 1.5`
- `gcloud` authenticated for the target project
- Billing-enabled GCP project
- Google OAuth client credentials (client ID + secret) and a refresh token for the bot calendar owner account
- Calendar API enabled on that project (Terraform enables it)
- A target personal Google account email for invites

## Bot Calendar Setup

- Use a Google account as the bot organiser (OAuth owner).
- The functions auto-create calendars when needed:
  - `Prospective Hackathons` (invite + RSVP workflow source)
  - `Committed Hackathons` (accepted events copied here)
- You can toggle visibility independently in Google Calendar by checking/unchecking each calendar.

## Configure Terraform

1. Copy the example vars file:

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

2. Fill real values in `terraform.tfvars` (never commit secrets):

- `gemini_api_key`
- `target_account_email`
- `google_oauth_client_id`
- `google_oauth_client_secret`
- `google_oauth_refresh_token`
- `discovery_window_days` (default `35`)
- `max_discovery_results` (default `80`)
- `quality_score_threshold` (default `0.65`)
- `bot_calendar_id` (legacy/unused by runtime; keep `"primary"` to satisfy current Terraform variable)
- `calendar_webhook_token` (long random string)

## OAuth Setup (One-Time)

1. In Google Cloud Console, create an OAuth client for a Desktop app.
2. Enable `Google Calendar API` and `Gemini API` in the same project.
3. Authorize scope `https://www.googleapis.com/auth/calendar` for the bot organiser account and obtain a refresh token.
4. Put these values in `terraform.tfvars`:
   - `google_oauth_client_id`
   - `google_oauth_client_secret`
   - `google_oauth_refresh_token`

## Deploy

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

After apply, note:

- `webhook_function_uri` output (used by Google Calendar watch renewal internally)
- Scheduler jobs created:
  - Weekly agent run: Monday 9:00 AEST (`Australia/Brisbane`)
  - Channel renewal: every 6 days

## Function Behavior Details

### Agent (`functions/agent/main.py`)

- Reads bundled `SKILLS.md` at runtime.
- Sends entire `SKILLS.md` content to Gemini in prompt.
- Uses search grounding (`google_search`) in Gemini request.
- Uses `gemini_model` (default `gemini-2.5-flash`).
- Uses discovery horizon (`discovery_window_days`) and max candidate cap (`max_discovery_results`).
- Uses weighted quality scoring and only creates invites when score >= `quality_score_threshold`.
- Performs:
  - Discovery stage: collect candidate event pages (Devpost/MLH/Devfolio/UQ/QUT/community sources and similar)
  - Validation stage: fetch candidate page text, verify event genuineness and SKILLS fit
- Normalizes URL and hashes it as Firestore doc key.
- Creates all-day event using `start.date` and `end.date` (`end + 1 day` convention).
- Creates/fetches `Prospective Hackathons` calendar and writes events there.
- Sets `source.url` so the event has a clickable source link in Calendar UI.

### Webhook (`functions/webhook/main.py`)

- Default path handles Calendar push notifications.
- Validates `X-Goog-Channel-Token` against Secret Manager value.
- Uses stored sync token to pull changed events from `Prospective Hackathons`.
- Checks attendee response status for target email.
- Copies accepted event into `Committed Hackathons` calendar.
- Updates Firestore status (`committed` / `declined`).
- `?action=renew` path rotates watch channel and stores fresh channel metadata.

## SKILLS.md Updates

`SKILLS.md` is bundled into the agent function package.

To update filtering criteria:

1. Edit `functions/agent/SKILLS.md`
2. Re-run `terraform apply` (or redeploy function)

## Security Notes

- No secrets are hardcoded in source.
- Secrets are loaded from Secret Manager at runtime.
- Webhook function is public for Calendar push delivery, but push notifications are authenticated by channel token.
- Renewal endpoint requires Cloud Scheduler OIDC token validation.

## Operational Notes

- Firestore stores all processed URLs including filtered ones to prevent re-evaluation.
- Push channel max TTL is 7 days; renewal schedule is set to every 6 days.
- If Calendar incremental sync token expires (`410`), webhook falls back to full sync and continues.

## Vector Cache Options

For current dedup/avoid-rescan, Firestore is sufficient and already serverless.

If you want semantic near-duplicate matching (same event, different titles/pages), practical serverless options are:

- BigQuery + Vector Search (native GCP, fully managed/serverless)
- Vertex AI Vector Search (managed ANN service; higher complexity/cost)
- Pinecone Serverless (external SaaS)
