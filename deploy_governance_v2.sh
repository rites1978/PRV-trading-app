#!/usr/bin/env bash
# ==============================================================================
# PRV CAPITAL | SPRINT 3/4 AUTOMATED DEPLOYMENT & ROLLBACK SCRIPT
# ==============================================================================
set -e

BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
DB_FILE="prv_capital.db"
MIGRATION_FILE="src/database/migrations/002_governance_tooling.sql"

echo "🏛️ STARTING GOVERNANCE TOOLING DEPLOYMENT..."

# 1. Create Pre-Deployment Backup
echo "📦 Step 1: Creating database backup..."
mkdir -p "$BACKUP_DIR"
if [ -f "$DB_FILE" ]; then
    cp "$DB_FILE" "$BACKUP_DIR/$DB_FILE.bak"
    echo "✅ Backup created at $BACKUP_DIR/$DB_FILE.bak"
fi

# 2. Apply SQLite Database Migration
echo "🗄️ Step 2: Applying schema migration..."
if [ -f "$MIGRATION_FILE" ]; then
    sqlite3 "$DB_FILE" < "$MIGRATION_FILE"
    echo "✅ Migration 002 applied successfully."
else
    echo "❌ Migration file $MIGRATION_FILE not found! Aborting."
    exit 1
fi

# 3. Execute Comprehensive Automated Test Suite
echo "🧪 Step 3: Running automated test suite..."
PYTHON_BIN=$(which python3 || which python3.11 || which python)
PYTHONPATH=. $PYTHON_BIN -m unittest discover tests

if [ $? -eq 0 ]; then
    echo "✅ All unit and integration tests passed with 100% success."
else
    echo "🚨 TESTS FAILED! Rolling back database..."
    cp "$BACKUP_DIR/$DB_FILE.bak" "$DB_FILE"
    echo "⏪ Rollback complete. Aborting deployment."
    exit 1
fi

echo "=============================================================================="
echo "🎯 DEPLOYMENT COMPLETE | GOVERNANCE INFRASTRUCTURE ONLINE | STRATEGY FROZEN"
echo "=============================================================================="
