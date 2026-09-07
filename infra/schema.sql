-- Run after the SQLAlchemy tables are created (Base.metadata.create_all),
-- or fold into an Alembic migration in production.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE resumes ADD COLUMN IF NOT EXISTS embedding vector(384);

-- IVFFlat index for approximate nearest-neighbor search once resume volume
-- justifies it (recruiter-side candidate-pool ranking, blueprint Section
-- "B2B expansion"). Skip this until there's enough row volume for IVFFlat
-- to be worth the build cost.
-- CREATE INDEX IF NOT EXISTS resumes_embedding_idx
--   ON resumes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
