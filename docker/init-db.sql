-- This script runs automatically when the PostgreSQL container starts for the first time.
-- It enables the pgvector extension for vector similarity search.
-- TimescaleDB is already enabled by the timescaledb-ha image.

CREATE EXTENSION IF NOT EXISTS vector;
