SHELL := /bin/bash
include env.sh

KUBECTL ?= kubectl
K3S_VERSION ?= v1.37.2+k3s1
HELM_VERSION ?= v4.3.2
K6_VERSION ?= v2.4.0
VPA_VERSION ?= 1.8.1
KPS_CHART_VERSION ?= 93.4.1

.PHONY: help up tools k3s vpa base status top logs health pf events node down uninstall-k3s monitoring rules dashboard reset scenario compare

help:
	@echo "make up            install tools/k3s/VPA + base + monitoring + rules + dashboard"
	@echo "make status        nodes, deployment, pods, services"
	@echo "make health        port-forward + GET readiness endpoint"
	@echo "make pf            port-forward svc/ocr to 127.0.0.1:8884 (foreground)"
	@echo "make top           kubectl top nodes/pods"
	@echo "make logs          last 100 log lines of the OCR pod"
	@echo "make events        recent namespace events"
	@echo "make node          show node allocatable resources"
	@echo "make monitoring    install/upgrade kube-prometheus-stack"
	@echo "make rules         apply recording rules (envsubst from env.sh)"
	@echo "make dashboard     apply Grafana dashboard ConfigMap"
	@echo "make reset         remove autoscalers, return to 1 replica + cooldown"
	@echo "make scenario SCENARIO=B-hpa-50 REP=1   run one experiment"
	@echo "make compare       build results/comparison.{csv,md}"
	@echo "make down          delete k8s/base resources (asks for confirmation)"
	@echo "make uninstall-k3s remove the whole k3s cluster (asks for confirmation)"

up: tools k3s vpa base monitoring rules dashboard

tools:
	@if ! command -v helm >/dev/null 2>&1; then \
		curl -fsSL https://get.helm.sh/helm-$(HELM_VERSION)-linux-amd64.tar.gz -o /tmp/helm.tgz && \
		tar -xzf /tmp/helm.tgz -C /tmp && sudo install -m 0755 /tmp/linux-amd64/helm /usr/local/bin/helm; \
	fi
	@if ! command -v k6 >/dev/null 2>&1; then \
		curl -fsSL https://github.com/grafana/k6/releases/download/$(K6_VERSION)/k6-$(K6_VERSION)-linux-amd64.tar.gz -o /tmp/k6.tgz && \
		tar -xzf /tmp/k6.tgz -C /tmp && sudo install -m 0755 /tmp/k6-$(K6_VERSION)-linux-amd64/k6 /usr/local/bin/k6; \
	fi

vpa:
	@if $(KUBECTL) get crd verticalpodautoscalers.autoscaling.k8s.io >/dev/null 2>&1; then \
		echo "VPA CRD already installed"; \
	else \
		rm -rf /tmp/vpa-autoscaler && \
		git clone --depth 1 --branch vertical-pod-autoscaler-$(VPA_VERSION) \
			https://github.com/kubernetes/autoscaler.git /tmp/vpa-autoscaler && \
		cd /tmp/vpa-autoscaler/vertical-pod-autoscaler && bash hack/vpa-up.sh; \
	fi

k3s:
	@if command -v k3s >/dev/null 2>&1; then \
		echo "k3s already installed: $$(k3s --version | head -1)"; \
	else \
		curl -fsSL https://get.k3s.io -o /tmp/k3s-install.sh && \
		sudo INSTALL_K3S_VERSION=$(K3S_VERSION) sh /tmp/k3s-install.sh \
			--write-kubeconfig-mode 644 --disable traefik --disable servicelb; \
	fi
	@mkdir -p $(HOME)/.kube
	@sudo cp /etc/rancher/k3s/k3s.yaml $(HOME)/.kube/config
	@sudo chown $$(id -u):$$(id -g) $(HOME)/.kube/config
	@chmod 600 $(HOME)/.kube/config
	@$(KUBECTL) wait --for=condition=Ready node/$$(hostname) --timeout=120s

base:
	$(KUBECTL) apply -k k8s/base
	$(KUBECTL) -n $(NAMESPACE) rollout status deploy/ocr --timeout=180s

status:
	$(KUBECTL) get nodes -o wide
	$(KUBECTL) -n $(NAMESPACE) get deploy,rs,pods -o wide
	$(KUBECTL) -n $(NAMESPACE) get svc

top:
	$(KUBECTL) top nodes
	$(KUBECTL) -n $(NAMESPACE) top pods

logs:
	$(KUBECTL) -n $(NAMESPACE) logs -l app=ocr --tail=100 --all-containers

events:
	$(KUBECTL) -n $(NAMESPACE) get events --sort-by=.lastTimestamp | tail -30

node:
	@$(KUBECTL) describe node | sed -n '/Allocatable:/,/System Info:/p'

pf:
	$(KUBECTL) -n $(NAMESPACE) port-forward svc/ocr 8884:8884

health:
	@$(KUBECTL) -n $(NAMESPACE) port-forward svc/ocr 18884:8884 >/tmp/ocr-pf.log 2>&1 & \
	pid=$$!; trap "kill $$pid 2>/dev/null" EXIT; sleep 2; \
	curl -fsS --max-time 5 http://127.0.0.1:18884/.well-known/health/ready; echo

down:
	@read -p "Delete namespace $(NAMESPACE) and all its objects? Type yes: " a; \
	[ "$$a" = "yes" ] && $(KUBECTL) delete -k k8s/base --ignore-not-found || echo "aborted"

uninstall-k3s:
	@read -p "Remove the whole k3s cluster from this host? Type yes: " a; \
	[ "$$a" = "yes" ] && sudo /usr/local/bin/k3s-uninstall.sh || echo "aborted"

monitoring: tools
	@helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
	@helm repo update >/dev/null 2>&1 || true
	helm upgrade --install kps prometheus-community/kube-prometheus-stack \
		--version $(KPS_CHART_VERSION) -n monitoring --create-namespace \
		-f monitoring/kube-prometheus-stack-values.yaml --wait --timeout 10m

rules:
	envsubst '$${NODE_PRICE_PER_HOUR} $${NODE_VCPU} $${NODE_RAM_GIB}' \
		< monitoring/recording-rules.yaml | $(KUBECTL) apply -f -

dashboard:
	$(KUBECTL) apply -k monitoring/dashboards

reset:
	bash scripts/reset.sh

scenario:
	bash scripts/run-scenario.sh $(SCENARIO) $(REP)

compare:
	python3 scripts/compare.py
