# ==============================================================================
# IAM & Service Accounts — Cloud Build CI/CD & Cloud Run Runtime
# ==============================================================================

locals {
  cloudbuild_sa_email = "128541051144@cloudbuild.gserviceaccount.com"
  cloudbuild_roles = toset([
    "roles/run.admin",
    "roles/iam.serviceAccountUser",
    "roles/artifactregistry.writer",
  ])
}

# ------------------------------------------------------------------------------
# Runtime Service Account for Cloud Run ('smg-serverless-sa')
# ------------------------------------------------------------------------------
resource "google_service_account" "runtime_sa" {
  project      = var.project_id
  account_id   = "smg-serverless-sa"
  display_name = "SMG Serverless App Runtime Service Account"
  description  = "Dedicated least-privilege runtime identity for the smg-serverless-app Cloud Run service"
}

# ------------------------------------------------------------------------------
# Cloud Build Service Account Roles
# (roles/run.admin, roles/iam.serviceAccountUser, roles/artifactregistry.writer)
# ------------------------------------------------------------------------------
resource "google_project_iam_member" "cloudbuild_cicd_roles" {
  for_each = local.cloudbuild_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${local.cloudbuild_sa_email}"
}

# ------------------------------------------------------------------------------
# Public Invoker Access (handled automatically by Cloud Run --allow-unauthenticated,
# or uncomment after service is provisioned)
# ------------------------------------------------------------------------------
# resource "google_cloud_run_service_iam_member" "public_invoker" {
#   project  = var.project_id
#   location = var.region
#   service  = var.service_name
#   role     = "roles/run.invoker"
#   member   = "allUsers"
# }
