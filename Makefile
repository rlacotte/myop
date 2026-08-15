.PHONY: setup serve generate publish trigger voices test

setup:            ## Installe les dépendances puis configure la livraison GitHub
	uv sync
	uv run myop setup

serve:            ## Ouvre le dashboard (http://localhost:8484)
	uv run myop serve

generate:         ## Génère l'épisode du jour en local
	uv run myop generate

publish:          ## Publie dist/ sur GitHub Pages
	uv run myop publish

trigger:          ## Déclenche le workflow GitHub Actions
	uv run myop trigger

voices:           ## Liste les voix françaises
	uv run myop voices --current $$(grep '^voice:' config.yaml | awk '{print $$2}')

test:             ## Lance les tests
	uv sync --extra dev
	uv run pytest -q
