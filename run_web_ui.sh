#!/bin/bash
# Script to run the Trading Bot Web UI

echo "🚀 Starting Trading Bot Web UI..."
echo ""
echo "The dashboard will be available at:"
echo "  http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

cd "$(dirname "$0")"
python src/web_app.py
