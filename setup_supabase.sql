-- Supabase에서 실행할 SQL 스크립트
-- pgvector 확장 활성화
CREATE EXTENSION IF NOT EXISTS vector;

-- documents 테이블 생성
CREATE TABLE IF NOT EXISTS public.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    metadata JSONB,
    embedding VECTOR(768),  -- Gemini text-embedding-004는 768 차원
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 벡터 유사도 검색을 위한 인덱스 생성
CREATE INDEX IF NOT EXISTS documents_embedding_idx
ON public.documents
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- 유사도 검색 함수 생성
CREATE OR REPLACE FUNCTION match_documents(
    query_embedding VECTOR(768),
    match_threshold FLOAT DEFAULT 0.5,
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
        documents.id,
        documents.content,
        documents.metadata,
        1 - (documents.embedding <=> query_embedding) AS similarity
    FROM documents
    WHERE 1 - (documents.embedding <=> query_embedding) > match_threshold
    ORDER BY documents.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Row Level Security 활성화 (선택사항)
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

-- 모든 사용자가 읽기 가능하도록 정책 생성
CREATE POLICY "Anyone can read documents"
ON public.documents
FOR SELECT
USING (true);

-- 인증된 사용자만 쓰기 가능하도록 정책 생성
CREATE POLICY "Authenticated users can insert documents"
ON public.documents
FOR INSERT
WITH CHECK (true);
