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
