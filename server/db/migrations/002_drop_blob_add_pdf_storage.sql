-- Migration 002: Remove Azure Blob Storage dependency.
--
-- Generated resumes (PDF + LaTeX source) are now stored directly in the
-- sessions row instead of an external blob store. This keeps the whole
-- app on a single Postgres database (Supabase-compatible) with no other
-- storage service to provision.
--
-- Idempotent: safe to run multiple times.

BEGIN;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS pdf_data BYTEA,
    ADD COLUMN IF NOT EXISTS pdf_filename TEXT,
    ADD COLUMN IF NOT EXISTS latex_source TEXT;

ALTER TABLE sessions DROP COLUMN IF EXISTS blob_path;

COMMIT;
