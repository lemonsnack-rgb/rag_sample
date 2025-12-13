-- 기존 함수 삭제
DROP FUNCTION IF EXISTS match_documents(vector(768), float, int);

-- 유사도 검색 함수 재생성 (수정된 버전)
CREATE OR REPLACE FUNCTION match_documents(
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
AS $$
BEGIN
    RETURN QUERY
    SELECT
        public.documents.id,
        public.documents.content,
        public.documents.metadata,
        (1 - (public.documents.embedding <=> query_embedding)) AS similarity
    FROM public.documents
    WHERE public.documents.embedding IS NOT NULL
        AND (1 - (public.documents.embedding <=> query_embedding)) >= match_threshold
    ORDER BY public.documents.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
