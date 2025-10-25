#!/bin/bash

# Multi-Pair Trading Bot Startup Script
# Trades ALL pairs that have trained ML models

echo "🤖 Starting Multi-Pair Trading Bot..."
echo ""
echo "This bot will:"
echo "  ✓ Auto-discover all trained ML models"
echo "  ✓ Trade up to 5 pairs simultaneously"
echo "  ✓ Manage portfolio-level risk"
echo "  ✓ Only use models with >55% accuracy"
echo ""

# Create logs directory
mkdir -p logs

# Run multi-pair bot
docker-compose exec web-ui python -m src.multi_pair_bot
