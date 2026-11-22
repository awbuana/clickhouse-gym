.PHONY: up down client logs gym gym-setup

up:
	docker compose up -d

down:
	docker compose down

client:
	docker compose exec clickhouse clickhouse-client --password clickhouse

logs:
	docker compose logs -f clickhouse

gym:
	python3 gym/gym.py

gym-setup:
	python3 gym/gym.py --setup
