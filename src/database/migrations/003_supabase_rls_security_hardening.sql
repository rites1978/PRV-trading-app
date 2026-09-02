-- =============================================================================
-- Migration 003: PRV CAPITAL | SUPABASE RLS HARDENING & LEAST-PRIVILEGE ACCESS CONTROL
-- Target Database: PostgreSQL (Supabase public schema)
-- Security Classification: TOP_SECRET_FINANCIAL
-- Policy: STRICT DEFAULT-DENY (Zero Public/Anonymous Access)
-- =============================================================================

BEGIN;

-- 1. Enable Row-Level Security (RLS) on ALL Public Schema Tables
ALTER TABLE IF EXISTS public.trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.risk_telemetry ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.agent_weights ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.market_regimes ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.boardroom_debates ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.execution_journal ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.post_mortem_analysis ENABLE ROW LEVEL SECURITY;

-- 2. Force RLS for Table Owners (Prevents accidental bypass by table owner role)
ALTER TABLE IF EXISTS public.trades FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.risk_telemetry FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.agent_weights FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.market_regimes FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.boardroom_debates FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.execution_journal FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.post_mortem_analysis FORCE ROW LEVEL SECURITY;

-- 3. Explicitly Revoke ALL Permissions from Public and Anonymous Roles
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, public;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, public;
REVOKE ALL ON ALL ROUTINES IN SCHEMA public FROM anon, public;

-- 4. Drop Any Existing Permissive or Legacy Policies
DROP POLICY IF EXISTS "allow_all_anon" ON public.trades;
DROP POLICY IF EXISTS "allow_all_anon" ON public.risk_telemetry;
DROP POLICY IF EXISTS "allow_all_anon" ON public.agent_weights;
DROP POLICY IF EXISTS "allow_all_anon" ON public.market_regimes;
DROP POLICY IF EXISTS "allow_all_anon" ON public.boardroom_debates;
DROP POLICY IF EXISTS "allow_all_anon" ON public.execution_journal;
DROP POLICY IF EXISTS "allow_all_anon" ON public.post_mortem_analysis;

DROP POLICY IF EXISTS "public_read_trades" ON public.trades;
DROP POLICY IF EXISTS "public_read_telemetry" ON public.risk_telemetry;

-- 5. Grant Administrative Permissions Exclusively to service_role (Server-Side Backend Only)
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA public TO service_role;

-- 6. Create Explicit Backend Policies for service_role
CREATE POLICY "service_role_manage_trades" 
ON public.trades 
FOR ALL 
TO service_role 
USING (true) 
WITH CHECK (true);

CREATE POLICY "service_role_manage_risk_telemetry" 
ON public.risk_telemetry 
FOR ALL 
TO service_role 
USING (true) 
WITH CHECK (true);

CREATE POLICY "service_role_manage_agent_weights" 
ON public.agent_weights 
FOR ALL 
TO service_role 
USING (true) 
WITH CHECK (true);

CREATE POLICY "service_role_manage_market_regimes" 
ON public.market_regimes 
FOR ALL 
TO service_role 
USING (true) 
WITH CHECK (true);

CREATE POLICY "service_role_manage_boardroom_debates" 
ON public.boardroom_debates 
FOR ALL 
TO service_role 
USING (true) 
WITH CHECK (true);

CREATE POLICY "service_role_manage_execution_journal" 
ON public.execution_journal 
FOR ALL 
TO service_role 
USING (true) 
WITH CHECK (true);

CREATE POLICY "service_role_manage_post_mortem" 
ON public.post_mortem_analysis 
FOR ALL 
TO service_role 
USING (true) 
WITH CHECK (true);

-- 7. Future Object Security (Default Privileges Hardening)
-- Ensures that ANY newly created table, sequence, or function automatically inherits DEFAULT-DENY
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, public, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, public, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON ROUTINES FROM anon, public, authenticated;

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON ROUTINES TO service_role;

COMMIT;
