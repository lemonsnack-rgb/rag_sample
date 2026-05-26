-- Supabase DB repair script for the current rag_module.py
--
-- Run this in Supabase SQL Editor when the app connects to Supabase but
-- indexing/search fails because RPC functions, policies, or hybrid-search
-- columns are missing.
--
-- This script is non-destructive: it does not drop the documents table or
-- delete existing rows. If old rows were inserted with the wrong embedding
-- type/dimension, run the diagnostics at the bottom and re-index documents.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    metadata JSONB,
    embedding VECTOR(768),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS documents_embedding_idx
ON public.documents
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Anyone can read documents" ON public.documents;
DROP POLICY IF EXISTS "Authenticated users can insert documents" ON public.documents;
DROP POLICY IF EXISTS "Anyone can delete documents" ON public.documents;
DROP POLICY IF EXISTS "Anyone can update documents" ON public.documents;
DROP POLICY IF EXISTS "Enable read access for all users" ON public.documents;
DROP POLICY IF EXISTS "Enable insert for all users" ON public.documents;
DROP POLICY IF EXISTS "Enable update for all users" ON public.documents;
DROP POLICY IF EXISTS "Enable delete for all users" ON public.documents;

CREATE POLICY "Anyone can read documents"
ON public.documents
FOR SELECT
USING (true);

CREATE POLICY "Authenticated users can insert documents"
ON public.documents
FOR INSERT
WITH CHECK (true);

CREATE POLICY "Anyone can update documents"
ON public.documents
FOR UPDATE
USING (true)
WITH CHECK (true);

CREATE POLICY "Anyone can delete documents"
ON public.documents
FOR DELETE
USING (true);

CREATE OR REPLACE FUNCTION public.insert_document_safe(
    p_content TEXT,
    p_metadata JSONB,
    p_embedding_array FLOAT[]
)
RETURNS UUID
LANGUAGE plpgsql
AS $insert_document_safe$
DECLARE
    new_id UUID;
BEGIN
    INSERT INTO public.documents (content, metadata, embedding)
    VALUES (
        p_content,
        p_metadata,
        p_embedding_array::vector(768)
    )
    RETURNING id INTO new_id;

    RETURN new_id;
END;
$insert_document_safe$;

CREATE OR REPLACE FUNCTION public.match_documents(
    query_embedding VECTOR(768),
    match_threshold FLOAT DEFAULT 0.0,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    metadata JSONB,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $match_documents$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.content,
        d.metadata,
        (1 - (d.embedding <=> query_embedding))::FLOAT AS similarity
    FROM public.documents AS d
    WHERE d.embedding IS NOT NULL
      AND (1 - (d.embedding <=> query_embedding)) >= match_threshold
    ORDER BY d.embedding <=> query_embedding
    LIMIT match_count;
END;
$match_documents$;

ALTER TABLE public.documents
ADD COLUMN IF NOT EXISTS content_tsv TSVECTOR;

UPDATE public.documents
SET content_tsv = to_tsvector('simple', coalesce(content, ''))
WHERE content_tsv IS NULL;

CREATE OR REPLACE FUNCTION public.documents_content_tsv_trigger()
RETURNS trigger
LANGUAGE plpgsql
AS $documents_content_tsv_trigger$
BEGIN
    NEW.content_tsv := to_tsvector('simple', coalesce(NEW.content, ''));
    RETURN NEW;
END;
$documents_content_tsv_trigger$;

DROP TRIGGER IF EXISTS documents_content_tsv_update ON public.documents;
CREATE TRIGGER documents_content_tsv_update
    BEFORE INSERT OR UPDATE ON public.documents
    FOR EACH ROW
    EXECUTE FUNCTION public.documents_content_tsv_trigger();

CREATE INDEX IF NOT EXISTS documents_content_tsv_idx
ON public.documents
USING GIN(content_tsv);

CREATE OR REPLACE FUNCTION public.hybrid_search_documents(
    query_embedding VECTOR(768),
    query_text TEXT,
    match_threshold FLOAT DEFAULT 0.1,
    match_count INT DEFAULT 10,
    keyword_weight FLOAT DEFAULT 0.4
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    metadata JSONB,
    vector_similarity FLOAT,
    keyword_score FLOAT,
    hybrid_score FLOAT
)
LANGUAGE plpgsql
AS $hybrid_search_documents$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.content,
        d.metadata,
        (1 - (d.embedding <=> query_embedding))::FLOAT AS vector_similarity,
        ts_rank(d.content_tsv, plainto_tsquery('simple', query_text))::FLOAT AS keyword_score,
        (
            (1 - keyword_weight) * (1 - (d.embedding <=> query_embedding)) +
            keyword_weight * ts_rank(d.content_tsv, plainto_tsquery('simple', query_text))
        )::FLOAT AS hybrid_score
    FROM public.documents AS d
    WHERE d.embedding IS NOT NULL
      AND (
          (1 - (d.embedding <=> query_embedding)) >= match_threshold
          OR ts_rank(d.content_tsv, plainto_tsquery('simple', query_text)) > 0
      )
    ORDER BY hybrid_score DESC
    LIMIT match_count;
END;
$hybrid_search_documents$;

CREATE OR REPLACE FUNCTION public.hybrid_search_documents_doc_ranked(
    query_embedding VECTOR(768),
    query_text TEXT,
    match_threshold FLOAT DEFAULT 0.1,
    match_count INT DEFAULT 10,
    keyword_weight FLOAT DEFAULT 0.4,
    chunks_per_doc INT DEFAULT 2
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    metadata JSONB,
    vector_similarity FLOAT,
    keyword_score FLOAT,
    hybrid_score FLOAT
)
LANGUAGE plpgsql
AS $hybrid_search_documents_doc_ranked$
BEGIN
    RETURN QUERY
    WITH scored AS (
        SELECT
            d.id,
            d.content,
            d.metadata,
            coalesce(d.metadata->>'source', d.id::TEXT) AS source_key,
            (1 - (d.embedding <=> query_embedding))::FLOAT AS vector_similarity,
            ts_rank(d.content_tsv, plainto_tsquery('simple', query_text))::FLOAT AS keyword_score,
            (
                (1 - keyword_weight) * (1 - (d.embedding <=> query_embedding)) +
                keyword_weight * ts_rank(d.content_tsv, plainto_tsquery('simple', query_text))
            )::FLOAT AS hybrid_score
        FROM public.documents AS d
        WHERE d.embedding IS NOT NULL
          AND (
              (1 - (d.embedding <=> query_embedding)) >= match_threshold
              OR ts_rank(d.content_tsv, plainto_tsquery('simple', query_text)) > 0
          )
    ),
    ranked AS (
        SELECT
            scored.*,
            row_number() OVER (
                PARTITION BY scored.source_key
                ORDER BY scored.hybrid_score DESC
            ) AS chunk_rank,
            max(scored.hybrid_score) OVER (
                PARTITION BY scored.source_key
            ) AS source_score
        FROM scored
    )
    SELECT
        ranked.id,
        ranked.content,
        ranked.metadata,
        ranked.vector_similarity,
        ranked.keyword_score,
        ranked.hybrid_score
    FROM ranked
    WHERE ranked.chunk_rank <= greatest(chunks_per_doc, 1)
    ORDER BY ranked.source_score DESC, ranked.hybrid_score DESC
    LIMIT match_count;
END;
$hybrid_search_documents_doc_ranked$;

-- Diagnostics to run after the repair:
--
-- SELECT count(*) AS total_chunks FROM public.documents;
-- SELECT vector_dims(embedding) AS embedding_dims, count(*)
-- FROM public.documents
-- WHERE embedding IS NOT NULL
-- GROUP BY vector_dims(embedding);
-- SELECT routine_name
-- FROM information_schema.routines
-- WHERE routine_schema = 'public'
--   AND routine_name IN (
--       'insert_document_safe',
--       'match_documents',
--       'hybrid_search_documents',
--       'hybrid_search_documents_doc_ranked'
--   )
-- ORDER BY routine_name;
