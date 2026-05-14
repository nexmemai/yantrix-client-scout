SHELL := /usr/bin/env bash

.PHONY: deploy up down build logs ps

deploy:
	bash ./deploy.sh

up:
	docker compose --env-file .env up -d

down:
	docker compose --env-file .env down

build:
	docker compose --env-file .env build

logs:
	docker compose --env-file .env logs -f --tail=100

ps:
	docker compose --env-file .env ps
