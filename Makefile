.PHONY: \
	deploy \
	deploy-infra \
	deploy-ui \
	help

.DEFAULT_GOAL := help

ENVIRONMENT ?= dev
AWS_PROFILE ?= nava-sandbox
AWS_ARGS := --profile $(AWS_PROFILE)
TF_DIR := infra/environments/$(ENVIRONMENT)

deploy: ## Deploy everything (infra + UI)
deploy: deploy-infra deploy-ui

deploy-infra: ## Deploy infrastructure (Docker image + Terraform)
	$(MAKE) -C infra infra-deploy ENVIRONMENT=$(ENVIRONMENT) AWS_PROFILE=$(AWS_PROFILE)

deploy-ui: ## Build admin UI and sync to S3 + invalidate CloudFront
	@echo "Building admin UI..."
	cd admin-ui && npm run build
	@BUCKET=$$(terraform -chdir="$(TF_DIR)" output -raw admin_ui_bucket) && \
	DIST_ID=$$(terraform -chdir="$(TF_DIR)" output -raw admin_ui_distribution_id) && \
	echo "Syncing to s3://$$BUCKET..." && \
	aws s3 sync admin-ui/ s3://$$BUCKET \
		--exclude "node_modules/*" \
		--exclude "package*.json" \
		--exclude ".gitignore" \
		--exclude "js/*" \
		--exclude "LICENSE" \
		--exclude "README.md" \
		--exclude "config.example.json" \
		--exclude "docs/*" \
		$(AWS_ARGS) \
		--delete && \
	echo "Invalidating CloudFront cache..." && \
	aws cloudfront create-invalidation \
		--distribution-id $$DIST_ID \
		--paths "/*" \
		$(AWS_ARGS) \
		--no-cli-pager && \
	echo "UI deployed: https://$$(terraform -chdir="$(TF_DIR)" output -raw admin_ui_url | sed 's|https://||')"

help: ## Show help
	@grep -Eh '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "ENVIRONMENT=$(ENVIRONMENT)  AWS_PROFILE=$(AWS_PROFILE)"
