#!/bin/sh
# Startup script for trading bot with TensorBoard

echo "Starting TensorBoard..."
python -m tensorboard.main --logdir logs/rl_tensorboard --bind_all --port 6006 &

echo "Starting Flask web app..."
python src/web_app.py
