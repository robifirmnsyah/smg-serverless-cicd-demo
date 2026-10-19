# ==============================================================================
# Input Variables — Cloud Run Serverless CI/CD Showcase
# ==============================================================================

variable "project_id" {
  description = "Google Cloud Project ID hosting the Serverless CI/CD showcase"
  type        = string
  default     = "dev-robifirmansyah"
}

variable "region" {
  description = "Google Cloud region for Artifact Registry and Cloud Run (Jakarta)"
  type        = string
  default     = "asia-southeast2"
}

variable "service_name" {
  description = "Name of the managed Google Cloud Run service"
  type        = string
  default     = "smg-serverless-app"
}

variable "repository_name" {
  description = "Artifact Registry Docker repository ID"
  type        = string
  default     = "smg-serverless-repo"
}
