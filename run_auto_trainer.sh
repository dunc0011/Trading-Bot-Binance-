#!/bin/bash

# Auto-Trainer Startup Script
# Runs the intelligent auto-trainer that discovers and trains models automatically

echo "🤖 Starting Auto-Trainer..."
echo "This will:"
echo "  - Discover top 20 USDT pairs by volume"
echo "  - Train ML models automatically"
echo "  - Retrain models weekly to keep them fresh"
echo ""

# Create logs directory
mkdir -p logs

# Run auto-trainer
docker-compose exec trading-bot python -m src.utils.auto_trainer
