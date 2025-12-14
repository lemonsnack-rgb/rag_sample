-- Supabase 완전 초기화 스크립트
--
-- 사용법:
-- 1. Supabase 대시보드 → SQL Editor
-- 2. 이 스크립트 전체 복사 & 붙여넣기
-- 3. RUN 클릭
--
-- 주의: 모든 데이터가 삭제됩니다!

-- 1. 기존 테이블 완전 삭제 (CASCADE = 관련 인덱스, 함수 모두 삭제)
DROP TABLE IF EXISTS public.documents CASCADE;

-- 2. pgvector 확장 활성화 (이미 있어도 무방)
CREATE EXTENSION IF NOT EXISTS vector;

-- 3. documents 테이블 재생성
CREATE TABLE public.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    metadata JSONB,
    embedding VECTOR(768),  -- Google embedding-001: 768차원
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. 벡터 유사도 검색 인덱스 생성
CREATE INDEX documents_embedding_idx
ON public.documents
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- 5. Row Level Security 활성화
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

-- 6. RLS 정책 생성 (모든 작업 허용)
CREATE POLICY "Anyone can read documents"
ON public.documents
FOR SELECT
USING (true);

CREATE POLICY "Authenticated users can insert documents"
ON public.documents
FOR INSERT
WITH CHECK (true);

CREATE POLICY "Anyone can delete documents"
ON public.documents
FOR DELETE
USING (true);

CREATE POLICY "Anyone can update documents"
ON public.documents
FOR UPDATE
USING (true);

-- 7. 유사도 검색 함수 재생성
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

-- 완료 메시지
DO $$
BEGIN
    RAISE NOTICE '✅ Supabase 초기화 완료!';
    RAISE NOTICE '다음 단계: Streamlit에서 "전체 재색인" 실행';
END $$;
