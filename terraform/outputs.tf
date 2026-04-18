output "agent_function_name" {
  value = google_cloudfunctions2_function.agent.name
}

output "webhook_function_uri" {
  value = google_cloudfunctions2_function.webhook.service_config[0].uri
}

output "agent_pubsub_topic" {
  value = google_pubsub_topic.agent_schedule.id
}

output "renew_scheduler_job" {
  value = google_cloud_scheduler_job.renew_channel.name
}

output "weekly_scheduler_job" {
  value = google_cloud_scheduler_job.agent_weekly.name
}
