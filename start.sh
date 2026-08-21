#!/usr/bin/env bash
set -e

echo "========================================================"
echo "🏛️ STARTING PRV CAPITAL QUANTITATIVE TRADING PLATFORM"
echo "========================================================"

# Run database migrations / table initialisation
python -c "from src.database.db import db; print('✅ Database Initialized.')"

# Launch supervisor if installed, or start services
if command -v supervisord >/dev/null 2>&1; then
    exec supervisord -c supervisord.conf
else
    # Fallback background execution
    uvicorn src.api.routes:app --host 0.0.0.0 --port 8000 &
    exec streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
fi
