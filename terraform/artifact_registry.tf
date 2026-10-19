# ==============================================================================
# Google Artifact Registry — Container Image Repository
# ==============================================================================

resource "google_artifact_registry_repository" "smg_repo" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_name
  description   = "Docker container repository for Cloud Run Serverless CI/CD & Canary Showcase"
  format        = "DOCKER"

  labels = {
    environment = "showcase"
    managed_by  = "terraform"
    service     = var.service_name
  }
}
