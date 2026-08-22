#!/usr/bin/env bash
set -e

echo "========================================================"
echo "🏛️ STARTING PRV CAPITAL QUANTITATIVE TRADING PLATFORM"
echo "========================================================"

# Run database migrations / table initialisation
python -c "from src.database.db import db; print('✅ Database Initialized.')"

# Launch Unified FastAPI Gateway directly on Render's dynamic $PORT
TARGET_PORT="${PORT:-8000}"
echo "🌐 Binding Unified FastAPI Gateway to 0.0.0.0:${TARGET_PORT}"
exec uvicorn main:app --host 0.0.0.0 --port "${TARGET_PORT}"
