-- 하이브리드 검색을 위한 Supabase 설정
-- 이 SQL을 Supabase SQL Editor에서 실행하세요

-- 1. Full-Text Search를 위한 tsvector 컬럼 추가
ALTER TABLE documents
ADD COLUMN IF NOT EXISTS content_tsv tsvector;

-- 2. 기존 데이터에 대해 tsvector 생성
UPDATE documents
SET content_tsv = to_tsvector('simple', content);

-- 3. 자동 업데이트 트리거 생성
CREATE OR REPLACE FUNCTION documents_content_tsv_trigger()
RETURNS trigger AS $$
BEGIN
    NEW.content_tsv := to_tsvector('simple', NEW.content);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS documents_content_tsv_update ON documents;
CREATE TRIGGER documents_content_tsv_update
    BEFORE INSERT OR UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION documents_content_tsv_trigger();

-- 4. Full-Text Search 인덱스 생성
CREATE INDEX IF NOT EXISTS documents_content_tsv_idx
ON documents USING GIN(content_tsv);

-- 5. 하이브리드 검색 함수 생성 (Vector + Keyword)
CREATE OR REPLACE FUNCTION hybrid_search_documents(
    query_embedding VECTOR(768),
    query_text TEXT,
    match_threshold FLOAT DEFAULT 0.1,
    match_count INT DEFAULT 10,
    keyword_weight FLOAT DEFAULT 0.3  -- 키워드 가중치 (0.3 = 30%)
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
AS $$
BEGIN
    RETURN QUERY
    SELECT
        documents.id,
        documents.content,
        documents.metadata,
        (1 - (documents.embedding <=> query_embedding)) AS vector_similarity,
        ts_rank(documents.content_tsv, plainto_tsquery('simple', query_text)) AS keyword_score,
        (
            (1 - keyword_weight) * (1 - (documents.embedding <=> query_embedding)) +
            keyword_weight * ts_rank(documents.content_tsv, plainto_tsquery('simple', query_text))
        ) AS hybrid_score
    FROM documents
    WHERE
        (1 - (documents.embedding <=> query_embedding)) > match_threshold
        OR ts_rank(documents.content_tsv, plainto_tsquery('simple', query_text)) > 0
    ORDER BY hybrid_score DESC
    LIMIT match_count;
END;
$$;

-- 사용 예시:
-- SELECT * FROM hybrid_search_documents(
--     query_embedding := '[0.1, 0.2, ...]'::vector(768),
--     query_text := '물리학 논문 투고',
--     match_threshold := 0.1,
--     match_count := 10,
--     keyword_weight := 0.3
-- );
