variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Primary region for Cloud Functions"
  type        = string
  default     = "australia-southeast1"
}

variable "timezone" {
  description = "Timezone for scheduler jobs"
  type        = string
  default     = "Australia/Brisbane"
}

variable "agent_schedule" {
  description = "Cron for weekly agent trigger"
  type        = string
  default     = "0 9 * * 1"
}

variable "renew_schedule" {
  description = "Cron for push channel renewal (must be < 7 days)"
  type        = string
  default     = "0 6 */6 * *"
}

variable "gemini_api_key" {
  description = "Gemini API key"
  type        = string
  sensitive   = true
}

variable "gemini_model" {
  description = "Gemini model ID for generateContent"
  type        = string
  default     = "gemini-2.5-flash"
}

variable "discovery_window_days" {
  description = "How many days ahead to scan for upcoming hackathons"
  type        = number
  default     = 35
}

variable "max_discovery_results" {
  description = "Upper bound of discovered candidates per run"
  type        = number
  default     = 80
}

variable "quality_score_threshold" {
  description = "Minimum quality score (0-1) required before creating an invite event"
  type        = number
  default     = 0.65
}

variable "target_account_email" {
  description = "Personal Google account email to invite"
  type        = string
  sensitive   = true
}

variable "google_oauth_client_id" {
  description = "OAuth client ID for Calendar API bot user"
  type        = string
  sensitive   = true
}

variable "google_oauth_client_secret" {
  description = "OAuth client secret for Calendar API bot user"
  type        = string
  sensitive   = true
}

variable "google_oauth_refresh_token" {
  description = "OAuth refresh token for Calendar API bot user"
  type        = string
  sensitive   = true
}

variable "bot_calendar_id" {
  description = "Calendar ID owned by bot organiser account"
  type        = string
}

variable "calendar_webhook_token" {
  description = "Shared secret for Google Calendar push channel token"
  type        = string
  sensitive   = true
}

variable "firestore_collection" {
  description = "Firestore collection for hackathon state"
  type        = string
  default     = "hackathons"
}

variable "system_collection" {
  description = "Firestore collection for internal system docs"
  type        = string
  default     = "_system"
}
