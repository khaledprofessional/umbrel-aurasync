# AuraSync development helpers

PYTHON ?= python
PNPM ?= pnpm
VENV ?= .venv

.PHONY: help venv install test build dev images

help:
	@echo "make install   Install backend and frontend dependencies"
	@echo "make test      Run the backend test suite and TypeScript build"
	@echo "make build     Build the production dashboard"
	@echo "make dev       Run backend + Vite dev server (Linux/macOS)"
	@echo "make images    Build the three container images locally"

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(VENV)/bin/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
	cd frontend && $(PNPM) install

test:
	cd backend && ../$(VENV)/bin/python -m pytest
	cd frontend && $(PNPM) run build

build:
	cd frontend && $(PNPM) run build

dev:
	bash scripts/dev.sh

images:
	docker build -t aurasync-backend:dev ./backend
	docker build -t aurasync-web:dev ./frontend
	docker build -t aurasync-openrgb:dev ./docker/openrgb
