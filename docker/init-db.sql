-- This script runs automatically when the PostgreSQL container starts for the first time.
-- It enables required extensions for vector search and AI capabilities.
-- TimescaleDB is already enabled by the timescaledb-ha image.

-- pgvector: vector data type, HNSW/IVFFlat indexes for similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- pgai: in-database AI functions (embeddings, chat, auto-vectorization)
-- Requires plpython3u (installed automatically as dependency)
CREATE EXTENSION IF NOT EXISTS ai CASCADE;
