.PHONY: help prep generate check-data up down mcp mcp-demo validate
.DEFAULT_GOAL := help

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

prep: ## raw CSVs -> data/prepped/ (see data/README.md for the download)
	docker compose run --rm prep

generate: ## data/prepped/ -> data/synthetic/, the findings the API serves
	docker compose run --rm generate

check-data: ## check data/ against data/checksums.txt (see data/README.md, step 4)
	docker compose run --rm prep python scripts/checksum_data.py

up: ## API on :8000, notebooks on :8888
	docker compose up --build

down:
	docker compose down

mcp-demo: ## drive the MCP server as an agent would; writes analysis/out_mcp_transcript.md
	uv run --python 3.12 --with-requirements requirements.lock.txt --with fastmcp \
	  python analysis/mcp_demo.py

mcp: ## run the MCP server for an agent client (needs uv + prep/generate)
	uv run --with-requirements requirements.lock.txt --with fastmcp python -m mcp_layer.server

validate: ## check your claims.json before submitting: make validate CLAIMS=claims.json
	python scripts/validate_submission.py --claims $(or $(CLAIMS),claims.json) $(if $(URL),--url $(URL),)
