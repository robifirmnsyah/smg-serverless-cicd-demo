# ==============================================================================
# Terraform Versions, Providers & Remote State Backend
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    bucket = "tfstate-hitachi-lab-dev-robifirmansyah"
    prefix = "smg-serverless-cicd"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
