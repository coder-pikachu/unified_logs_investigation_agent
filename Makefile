# NOVA 2.0 RCA Demo — one-command orchestration.
# Atlas is cloud (pre-provisioned); this brings up the local agent + UI, drives
# the Java simulator, and resets state between rehearsals.

SHELL := /bin/bash
ROOT  := $(shell pwd)
VENV  := $(ROOT)/.venv
PY    := $(VENV)/bin/python
RUN   := $(ROOT)/.run
JAVA_HOME ?= /opt/homebrew/opt/openjdk@21
JAR   := $(ROOT)/novasim/target/novasim.jar
AGENT_PORT ?= 8000
UI_PORT    ?= 5173

export PATH := $(JAVA_HOME)/bin:$(PATH)

.DEFAULT_GOAL := help
.PHONY: help up down seed sim demo demo-live replay reset atlas-provision agent ui build-sim health logs venv ui-install test test-unit eval validate check-no-embed

help: ## show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

venv: ## create venv + install agent deps (uv-aware; skips if already installed)
	@test -d $(VENV) || (command -v uv >/dev/null 2>&1 && uv venv $(VENV) || python3 -m venv $(VENV))
	@$(PY) -c "import nova_agent" 2>/dev/null || \
	  (command -v uv >/dev/null 2>&1 && VIRTUAL_ENV=$(VENV) uv pip install -e $(ROOT)/agent \
	   || $(PY) -m pip install -q -e $(ROOT)/agent)
	@echo "agent deps ready"

ui-install: ## install UI deps if needed
	@test -d $(ROOT)/ui/node_modules || (cd $(ROOT)/ui && npm install)

$(JAR): ## build the Java simulator jar
	@cd $(ROOT)/novasim && JAVA_HOME=$(JAVA_HOME) mvn -q -DskipTests package
build-sim: $(JAR) ## build novasim jar

agent: ## start the agent (FastAPI + change-stream watcher) in the background
	@mkdir -p $(RUN)
	@( cd $(ROOT)/agent && exec $(PY) -m nova_agent ) > $(RUN)/agent.log 2>&1 & echo $$! > $(RUN)/agent.pid
	@echo "agent starting on :$(AGENT_PORT) (log: .run/agent.log)"
	@for i in $$(seq 1 40); do curl -sf localhost:$(AGENT_PORT)/api/health >/dev/null 2>&1 && { echo "agent healthy"; break; }; sleep 0.5; done

ui: ui-install ## start the UI (Vite dev server) in the background
	@mkdir -p $(RUN)
	@( cd $(ROOT)/ui && exec npm run dev ) > $(RUN)/ui.log 2>&1 & echo $$! > $(RUN)/ui.pid
	@echo "ui starting on :$(UI_PORT) (log: .run/ui.log)"

up: venv agent ui ## bring up agent + UI locally (Atlas is cloud)
	@echo ""
	@echo "  Ops board:  http://localhost:5173"
	@echo "  Agent API:  http://localhost:8000/api/health"
	@echo "  Simulate:   make sim   (then type: fire eis-martech-brownout)"

down: ## stop agent + UI (by port + pid, reliable regardless of how they started)
	@for p in $(AGENT_PORT) $(UI_PORT); do \
	  pids=$$(lsof -ti tcp:$$p 2>/dev/null); \
	  if [ -n "$$pids" ]; then kill $$pids 2>/dev/null; echo "stopped listener on :$$p"; fi; \
	done
	@pkill -f "python -m nova_agent" 2>/dev/null || true
	@pkill -f "$(ROOT)/ui/node_modules/.bin/vite" 2>/dev/null || true
	@for s in agent ui; do \
	  if [ -f $(RUN)/$$s.pid ]; then kill $$(cat $(RUN)/$$s.pid) 2>/dev/null || true; rm -f $(RUN)/$$s.pid; fi; \
	done
	@sleep 0.5; echo "down: agent + UI stopped"

seed: venv ## seed sample audit rows + kb_docs knowledge base
	@$(PY) $(ROOT)/data/seed.py --kb

reset: venv ## clear all state (incidents/memory/store/checkpoints/audit) + reseed kb
	@$(PY) $(ROOT)/data/reset.py

atlas-provision: venv ## create/verify all collections + search/vector indexes (idempotent)
	@$(PY) $(ROOT)/atlas/indexes.py

sim: build-sim ## run the interactive simulator (type: status | scenarios | fire <id> | quit)
	@JAVA_HOME=$(JAVA_HOME) java -jar $(JAR) --rate 5

demo: up ## up + open the ops board; then run `make sim` in another shell
	@sleep 1; (command -v open >/dev/null && open http://localhost:5173) || echo "open http://localhost:5173"
	@echo "Now run 'make sim' in a second terminal and fire a scenario."

demo-live: ## guided end-to-end demo: reset -> traffic -> fire -> memory beat -> grep beat
	@bash $(ROOT)/scripts/demo.sh

replay: venv ## offline fallback: replay a recorded run with networking disabled
	@REPLAY_MODE=1 $(PY) $(ROOT)/agent/replay.py

health: ## check agent + UI health
	@curl -s localhost:8000/api/health || echo "agent down"; echo
	@curl -sf localhost:5173 >/dev/null 2>&1 && echo "ui up" || echo "ui down"

logs: ## tail agent log
	@tail -f $(RUN)/agent.log

test-unit: venv ## fast unit tests (deterministic core; no network)
	@$(PY) -c "import pytest" 2>/dev/null || (command -v uv >/dev/null 2>&1 && VIRTUAL_ENV=$(VENV) uv pip install -q pytest || $(PY) -m pip install -q pytest)
	@$(PY) -m pytest $(ROOT)/agent/tests -q

validate: venv ## validate seeded/generated docs against contract §1 shapes
	@$(PY) $(ROOT)/data/validate_shapes.py

eval: venv ## RCA eval: 8 scenario classes through the real graph (needs Atlas+Grove; >=7/8)
	@$(PY) $(ROOT)/agent/tests/eval_scenarios.py

check-no-embed: ## guardrail: no embedding client anywhere in /agent
	@! grep -rInE "embeddings\.create|\.embed\(|OpenAIEmbeddings|voyageai|VoyageAI|embed_query|embed_documents" $(ROOT)/agent \
	  && echo "OK — no embedding client in /agent" || (echo "FAIL — embedding call found" && exit 1)

test: test-unit validate check-no-embed ## unit tests + shape validation + no-embed guardrail
	@echo "unit + validate + no-embed: PASS  (run 'make eval' for the live 8-scenario RCA eval)"
