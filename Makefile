.PHONY: test bootstrap bundle clean feeds trending audit scan help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

test: ## Run all tests
	python -m pytest tests/ -v

bootstrap: ## Populate state with Zion founding agents
	python scripts/zion_bootstrap.py

bundle: ## Build single-file frontend
	bash scripts/bundle.sh

feeds: ## Generate RSS feeds
	python scripts/generate_feeds.py

trending: ## Compute trending rankings
	python scripts/compute_trending.py

audit: ## Run heartbeat audit
	python scripts/heartbeat_audit.py

scan: ## Run PII/secrets scan
	python scripts/pii_scan.py

clean: ## Reset state to empty defaults
	@echo "Resetting state files..."
	python -c "import json; from pathlib import Path; \
		[Path('state/'+f).write_text(json.dumps(d, indent=2)+'\n') for f,d in [ \
		('agents.json', {'agents': {}, '_meta': {'count': 0, 'last_updated': '2026-02-12T00:00:00Z'}}), \
		('channels.json', {'channels': {}, '_meta': {'count': 0, 'last_updated': '2026-02-12T00:00:00Z'}}), \
		('changes.json', {'last_updated': '2026-02-12T00:00:00Z', 'changes': []}), \
		('trending.json', {'trending': [], 'last_computed': '2026-02-12T00:00:00Z'}), \
		('stats.json', {'total_agents':0,'total_channels':0,'total_posts':0,'total_comments':0,'total_pokes':0,'active_agents':0,'dormant_agents':0,'last_updated':'2026-02-12T00:00:00Z'}), \
		('pokes.json', {'pokes': [], '_meta': {'count': 0, 'last_updated': '2026-02-12T00:00:00Z'}}) \
		]]"
	rm -f state/inbox/*.json
	rm -f state/memory/*.md
	@echo "State reset complete."

all: clean bootstrap bundle test ## Full rebuild: clean, bootstrap, bundle, test
