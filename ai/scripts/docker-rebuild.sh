#!/bin/bash
set -e

echo "Stopping existing containers..."
docker compose down

echo "Rebuilding images..."
docker compose build --no-cache

echo "Starting services..."
docker compose up -d

echo "Waiting for services to be healthy..."
sleep 10

docker compose ps

echo "Deployment complete:"
echo "API: http://localhost:8000"
echo "Dashboard: http://localhost:4200"
