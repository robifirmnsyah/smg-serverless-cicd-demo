# ==============================================================================
# Makefile — Cloud Run Serverless CI/CD & Canary Traffic Splitting Showcase
# ==============================================================================

PROJECT_ID      ?= dev-robifirmansyah
REGION          ?= asia-southeast2
SERVICE_NAME    ?= smg-serverless-app
AR_REPO         ?= smg-serverless-repo
IMAGE_URL       ?= $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(AR_REPO)/$(SERVICE_NAME)
TF_DIR          ?= terraform
APP_DIR         ?= app

.DEFAULT_GOAL := help

.PHONY: help init plan apply build-v1 build-v2 split-canary-20 split-canary-50 rollout-100-v2 rollback-v1 test-traffic

help: ## Show available targets for the Cloud Run CI/CD showcase
	@echo "=============================================================================="
	@echo " Cloud Run Serverless CI/CD Showcase — Automation Targets"
	@echo "=============================================================================="
	@echo " Project ID : $(PROJECT_ID)"
	@echo " Region     : $(REGION)"
	@echo " Service    : $(SERVICE_NAME)"
	@echo " Image URL  : $(IMAGE_URL)"
	@echo "------------------------------------------------------------------------------"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo "=============================================================================="

# ------------------------------------------------------------------------------
# Terraform Infrastructure Targets
# ------------------------------------------------------------------------------

init: ## Initialize Terraform working directory
	terraform -chdir=$(TF_DIR) init

plan: ## Preview Terraform infrastructure changes
	terraform -chdir=$(TF_DIR) plan -var="project_id=$(PROJECT_ID)" -var="region=$(REGION)"

apply: ## Apply Terraform infrastructure changes
	terraform -chdir=$(TF_DIR) apply -var="project_id=$(PROJECT_ID)" -var="region=$(REGION)" -auto-approve

# ------------------------------------------------------------------------------
# Container Build & Cloud Run Revision Deployment Targets
# ------------------------------------------------------------------------------

cloudbuild-v1: ## Submit Cloud Build to build v1.0.0 and deploy to Cloud Run
	gcloud builds submit --config=cloudbuild.yaml \
		--substitutions=_APP_VERSION=v1.0.0,_RELEASE_CHANNEL="Stable Production",_TAG=v1.0.0,_REVISION_TAG=stable,_ACCENT_COLOR=blue,_ENABLE_CANARY=false \
		--project=$(PROJECT_ID)

cloudbuild-v2: ## Submit Cloud Build to build v2.0.0 and deploy Canary (0% initial traffic)
	gcloud builds submit --config=cloudbuild-canary.yaml \
		--substitutions=_APP_VERSION=v2.0.0,_RELEASE_CHANNEL="Canary Preview",_TAG=v2.0.0,_REVISION_TAG=canary,_ACCENT_COLOR=emerald,_ENABLE_CANARY=true \
		--project=$(PROJECT_ID)

build-v1: ## Build & push v1.0.0 image, deploy v1 revision with tag 'stable'
	gcloud auth configure-docker $(REGION)-docker.pkg.dev --quiet
	docker build --build-arg APP_VERSION=v1.0.0 -t $(IMAGE_URL):v1.0.0 -t $(IMAGE_URL):latest $(APP_DIR)
	docker push $(IMAGE_URL):v1.0.0
	docker push $(IMAGE_URL):latest
	gcloud run deploy $(SERVICE_NAME) \
		--project $(PROJECT_ID) \
		--image $(IMAGE_URL):v1.0.0 \
		--region $(REGION) \
		--platform managed \
		--allow-unauthenticated \
		--min-instances 0 \
		--max-instances 10 \
		--service-account smg-serverless-sa@$(PROJECT_ID).iam.gserviceaccount.com \
		--port 8080 \
		--tag stable \
		--set-env-vars "APP_VERSION=v1.0.0,RELEASE_CHANNEL=Stable Production,ACCENT_COLOR=blue,ENABLE_CANARY_FEATURES=false"

build-v2: ## Build & push v2.0.0 image, deploy v2 canary revision with tag 'canary' (0% initial traffic)
	gcloud auth configure-docker $(REGION)-docker.pkg.dev --quiet
	docker build --build-arg APP_VERSION=v2.0.0 -t $(IMAGE_URL):v2.0.0 $(APP_DIR)
	docker push $(IMAGE_URL):v2.0.0
	gcloud run deploy $(SERVICE_NAME) \
		--project $(PROJECT_ID) \
		--image $(IMAGE_URL):v2.0.0 \
		--region $(REGION) \
		--platform managed \
		--allow-unauthenticated \
		--min-instances 0 \
		--max-instances 10 \
		--service-account smg-serverless-sa@$(PROJECT_ID).iam.gserviceaccount.com \
		--port 8080 \
		--tag canary \
		--no-traffic \
		--set-env-vars "APP_VERSION=v2.0.0,RELEASE_CHANNEL=Canary Preview,ACCENT_COLOR=emerald,ENABLE_CANARY_FEATURES=true"

# ------------------------------------------------------------------------------
# Progressive Canary Traffic Splitting & Rollback Targets
# ------------------------------------------------------------------------------

split-canary-20: ## Route 80% traffic to v1 (stable) and 20% traffic to v2 (canary)
	gcloud run services update-traffic $(SERVICE_NAME) \
		--project $(PROJECT_ID) \
		--region $(REGION) \
		--platform managed \
		--to-tags stable=80,canary=20

split-canary-50: ## Route 50% traffic to v1 (stable) and 50% traffic to v2 (canary)
	gcloud run services update-traffic $(SERVICE_NAME) \
		--project $(PROJECT_ID) \
		--region $(REGION) \
		--platform managed \
		--to-tags stable=50,canary=50

rollout-100-v2: ## Promote v2 (canary) to receive 100% production traffic
	gcloud run services update-traffic $(SERVICE_NAME) \
		--project $(PROJECT_ID) \
		--region $(REGION) \
		--platform managed \
		--to-tags canary=100

rollback-v1: ## Instant rollback: restore 100% traffic back to v1 (stable)
	gcloud run services update-traffic $(SERVICE_NAME) \
		--project $(PROJECT_ID) \
		--region $(REGION) \
		--platform managed \
		--to-tags stable=100

# ------------------------------------------------------------------------------
# Live Traffic Drill & Verification
# ------------------------------------------------------------------------------

test-traffic: ## Run Python traffic distribution & cold-start drill against live service
	python3 scripts/traffic_drill.py
