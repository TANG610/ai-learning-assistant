# Supabase PostgreSQL + pgvector setup

This app can use Supabase PostgreSQL for persistent documents, RSS articles,
conversation records, assessments, reports, and pgvector retrieval.

## Required Vercel environment variables

Use the Supabase pooled connection string for serverless deployments.

```env
DB_BACKEND=postgres
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-...pooler.supabase.com:6543/postgres
DB_SSLMODE=require

VECTOR_INDEX_ENABLED=true
VECTOR_BACKEND=pgvector
EMBEDDING_API_KEY=sk-...
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

Keep the existing LLM variables for chat completion:

```env
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
JWT_SECRET=<stable-random-secret>
```

## Runtime behavior

- If `DATABASE_URL` is set, the app initializes the PostgreSQL schema from
  `backend/migrations_postgres/001_init.sql`.
- Uploaded files are parsed into `documents.raw_text` and `document_chunks`.
- RSS/manual article bodies are stored in `news_articles.content`.
- With `VECTOR_BACKEND=pgvector`, chunk embeddings are written into
  `document_chunks.embedding` and semantic search reads from pgvector.
- Without an embedding key, uploads still store original text and keyword
  retrieval still works, but vector recall is skipped.

## Notes

- `EMBEDDING_DIMENSION` must match the embedding model.
- For `text-embedding-3-small`, use `1536`.
- For a different embedding provider/model, update both
  `EMBEDDING_API_MODEL` and `EMBEDDING_DIMENSION` before creating data.
