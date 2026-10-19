# ==============================================================================
# Outputs — Cloud Run Serverless CI/CD Showcase
# ==============================================================================

output "artifact_registry_repo" {
  description = "Full Artifact Registry Docker repository path"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.smg_repo.repository_id}"
}

output "cloud_run_service_name" {
  description = "Target Cloud Run managed service name"
  value       = var.service_name
}

output "cloud_run_region" {
  description = "Target Google Cloud region for the Cloud Run service"
  value       = var.region
}
