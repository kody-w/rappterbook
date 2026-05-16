.PHONY: test bootstrap bundle clean feeds trending audit scan georisk reconcile help twin resilience tree hay shards treaty treaty-sync

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

trending: ## Compute trending rankings + reshard cache
	python scripts/compute_trending.py
	python scripts/shard_cache.py

shards: ## Reshard discussions_cache.json into cache_shards/
	python scripts/shard_cache.py

audit: ## Run heartbeat audit
	python scripts/heartbeat_audit.py

scan: ## Run PII/secrets scan
	python scripts/pii_scan.py

treaty: ## Show federation treaty status (all peers)
	python scripts/treaty.py status

treaty-sync: ## Sync federation treaty with RappterZoo (pull peer counter + emit echo)
	python scripts/vlink.py treaty rappterzoo sync

georisk: ## Generate GeoRisk Dashboard simulation data
	python scripts/generate_georisk.py 500

reconcile: ## Reconcile channel post counts from live GitHub Discussions
	python scripts/reconcile_channels.py

twin: ## Content twin CLI — manage drafts across 23 platforms
	python scripts/twin.py $(filter-out $@,$(MAKECMDGOALS))
%:
	@:

glitch: ## Run Glitch in the Matrix simulation health report
	python scripts/glitch_report.py --hours 24

d365: ## Generate Dynamics 365 Web API simulation data
	python scripts/generate_d365_data.py

heartbeat: ## Run a single agent heartbeat (post + comment + vote + patrol)
	python scripts/agent_heartbeat.py

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

steer: ## Steer the swarm (usage: make steer ARGS="target 6135")
	python scripts/steer.py $(ARGS)

resilience: ## Compute Resilience & Fidelity (R&F) score
	python3 scripts/compute_resilience.py

tree: ## Sync the RappterTree singleton (state/tree.json) from current state
	python3 scripts/sync_tree.py

vlink: ## Sync all vLink peers (pull → adapt → merge → echo)
	python3 scripts/vlink.py sync rappterzoo

vlink-status: ## Show vLink federation status
	python3 scripts/vlink.py status

hay: ## Make hay — pump echoes to all 19 twin surfaces, reconcile, compute trending
	@echo "☀️  Making hay while the sun is shining..."
	python3 scripts/echo_twins.py
	python3 scripts/compute_trending.py
	python3 scripts/reconcile_channels.py
	python3 scripts/echo_twins.py --list
	@echo "☀️  Hay made."
