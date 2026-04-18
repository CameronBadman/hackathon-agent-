terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.30"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  required_services = [
    "artifactregistry.googleapis.com",
    "calendar-json.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudscheduler.googleapis.com",
    "eventarc.googleapis.com",
    "firestore.googleapis.com",
    "generativelanguage.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ]

  source_bucket_name = "${var.project_id}-hackathon-functions-src"
}

resource "google_project_service" "required" {
  for_each                   = toset(local.required_services)
  project                    = var.project_id
  service                    = each.key
  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = "australia-southeast1"
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "gemini-api-key"
  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "gemini_api_key" {
  secret      = google_secret_manager_secret.gemini_api_key.id
  secret_data = var.gemini_api_key
}

resource "google_secret_manager_secret" "target_email" {
  secret_id = "target-account-email"
  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "target_email" {
  secret      = google_secret_manager_secret.target_email.id
  secret_data = var.target_account_email
}

resource "google_secret_manager_secret" "google_oauth_client_id" {
  secret_id = "google-oauth-client-id"
  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "google_oauth_client_id" {
  secret      = google_secret_manager_secret.google_oauth_client_id.id
  secret_data = var.google_oauth_client_id
}

resource "google_secret_manager_secret" "google_oauth_client_secret" {
  secret_id = "google-oauth-client-secret"
  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "google_oauth_client_secret" {
  secret      = google_secret_manager_secret.google_oauth_client_secret.id
  secret_data = var.google_oauth_client_secret
}

resource "google_secret_manager_secret" "google_oauth_refresh_token" {
  secret_id = "google-oauth-refresh-token"
  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "google_oauth_refresh_token" {
  secret      = google_secret_manager_secret.google_oauth_refresh_token.id
  secret_data = var.google_oauth_refresh_token
}

resource "google_secret_manager_secret" "bot_calendar_id" {
  secret_id = "bot-calendar-id"
  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "bot_calendar_id" {
  secret      = google_secret_manager_secret.bot_calendar_id.id
  secret_data = var.bot_calendar_id
}

resource "google_secret_manager_secret" "calendar_webhook_token" {
  secret_id = "calendar-webhook-token"
  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "calendar_webhook_token" {
  secret      = google_secret_manager_secret.calendar_webhook_token.id
  secret_data = var.calendar_webhook_token
}

resource "google_service_account" "functions_runtime" {
  account_id   = "hackathon-functions-runtime"
  display_name = "Hackathon Functions Runtime"
}

resource "google_project_iam_member" "runtime_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.functions_runtime.email}"
}

resource "google_project_iam_member" "runtime_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.functions_runtime.email}"
}

resource "google_project_iam_member" "runtime_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.functions_runtime.email}"
}

resource "google_service_account" "scheduler_invoker" {
  account_id   = "hackathon-scheduler-invoker"
  display_name = "Hackathon Scheduler OIDC Invoker"
}

resource "google_service_account_iam_member" "scheduler_agent_token_creator" {
  service_account_id = google_service_account.scheduler_invoker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
}

resource "google_storage_bucket" "function_sources" {
  name                        = local.source_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  depends_on = [google_project_service.required]
}

data "archive_file" "agent_source" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/agent"
  output_path = "${path.module}/.agent.zip"
}

resource "google_storage_bucket_object" "agent_source" {
  name   = "agent-${data.archive_file.agent_source.output_md5}.zip"
  bucket = google_storage_bucket.function_sources.name
  source = data.archive_file.agent_source.output_path
}

resource "google_pubsub_topic" "agent_schedule" {
  name = "hackathon-agent-weekly"

  depends_on = [google_project_service.required]
}

resource "google_cloudfunctions2_function" "agent" {
  name     = "hackathon-agent"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "run_agent"
    source {
      storage_source {
        bucket = google_storage_bucket.function_sources.name
        object = google_storage_bucket_object.agent_source.name
      }
    }
  }

  service_config {
    timeout_seconds       = 540
    available_memory      = "512M"
    service_account_email = google_service_account.functions_runtime.email
    environment_variables = {
      PROJECT_ID                             = var.project_id
      FIRESTORE_COLLECTION                   = var.firestore_collection
      GEMINI_MODEL                           = var.gemini_model
      DISCOVERY_WINDOW_DAYS                  = tostring(var.discovery_window_days)
      MAX_DISCOVERY_RESULTS                  = tostring(var.max_discovery_results)
      QUALITY_SCORE_THRESHOLD                = tostring(var.quality_score_threshold)
      GEMINI_API_KEY_SECRET_NAME             = google_secret_manager_secret.gemini_api_key.secret_id
      TARGET_EMAIL_SECRET_NAME               = google_secret_manager_secret.target_email.secret_id
      GOOGLE_OAUTH_CLIENT_ID_SECRET_NAME     = google_secret_manager_secret.google_oauth_client_id.secret_id
      GOOGLE_OAUTH_CLIENT_SECRET_SECRET_NAME = google_secret_manager_secret.google_oauth_client_secret.secret_id
      GOOGLE_OAUTH_REFRESH_TOKEN_SECRET_NAME = google_secret_manager_secret.google_oauth_refresh_token.secret_id
      BOT_CALENDAR_ID_SECRET_NAME            = google_secret_manager_secret.bot_calendar_id.secret_id
    }
  }

  event_trigger {
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.agent_schedule.id
    trigger_region = var.region
    retry_policy   = "RETRY_POLICY_RETRY"
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.runtime_firestore,
    google_project_iam_member.runtime_secret_accessor,
    google_project_iam_member.runtime_logging,
  ]
}

data "archive_file" "webhook_source" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/webhook"
  output_path = "${path.module}/.webhook.zip"
}

resource "google_storage_bucket_object" "webhook_source" {
  name   = "webhook-${data.archive_file.webhook_source.output_md5}.zip"
  bucket = google_storage_bucket.function_sources.name
  source = data.archive_file.webhook_source.output_path
}

resource "google_cloudfunctions2_function" "webhook" {
  name     = "hackathon-webhook"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "webhook_entrypoint"
    source {
      storage_source {
        bucket = google_storage_bucket.function_sources.name
        object = google_storage_bucket_object.webhook_source.name
      }
    }
  }

  service_config {
    timeout_seconds       = 540
    available_memory      = "512M"
    service_account_email = google_service_account.functions_runtime.email
    environment_variables = {
      PROJECT_ID                             = var.project_id
      FIRESTORE_COLLECTION                   = var.firestore_collection
      SYSTEM_COLLECTION                      = var.system_collection
      TARGET_EMAIL_SECRET_NAME               = google_secret_manager_secret.target_email.secret_id
      GOOGLE_OAUTH_CLIENT_ID_SECRET_NAME     = google_secret_manager_secret.google_oauth_client_id.secret_id
      GOOGLE_OAUTH_CLIENT_SECRET_SECRET_NAME = google_secret_manager_secret.google_oauth_client_secret.secret_id
      GOOGLE_OAUTH_REFRESH_TOKEN_SECRET_NAME = google_secret_manager_secret.google_oauth_refresh_token.secret_id
      BOT_CALENDAR_ID_SECRET_NAME            = google_secret_manager_secret.bot_calendar_id.secret_id
      WEBHOOK_SECRET_NAME                    = google_secret_manager_secret.calendar_webhook_token.secret_id
      SCHEDULER_INVOKER_SA                   = google_service_account.scheduler_invoker.email
    }
    ingress_settings = "ALLOW_ALL"
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.runtime_firestore,
    google_project_iam_member.runtime_secret_accessor,
    google_project_iam_member.runtime_logging,
  ]
}

resource "google_cloud_run_service_iam_member" "webhook_public_invoker" {
  location = var.region
  service  = google_cloudfunctions2_function.webhook.service_config[0].service
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_scheduler_job" "agent_weekly" {
  name      = "hackathon-agent-weekly"
  schedule  = var.agent_schedule
  time_zone = var.timezone

  pubsub_target {
    topic_name = google_pubsub_topic.agent_schedule.id
    data       = base64encode("{\"source\":\"cloud-scheduler\"}")
  }

  depends_on = [google_cloudfunctions2_function.agent]
}

resource "google_cloud_scheduler_job" "renew_channel" {
  name      = "hackathon-calendar-renew"
  schedule  = var.renew_schedule
  time_zone = var.timezone

  http_target {
    uri         = "${google_cloudfunctions2_function.webhook.service_config[0].uri}?action=renew"
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = google_cloudfunctions2_function.webhook.service_config[0].uri
    }
  }

  depends_on = [
    google_cloudfunctions2_function.webhook,
    google_service_account_iam_member.scheduler_agent_token_creator,
  ]
}
