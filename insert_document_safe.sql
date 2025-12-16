-- 임베딩 안전 저장 함수
-- SupabaseVectorStore의 TEXT 저장 문제 해결
-- FLOAT[] → VECTOR(768) 명시적 변환

CREATE OR REPLACE FUNCTION insert_document_safe(
    p_content TEXT,
    p_metadata JSONB,
    p_embedding_array FLOAT[]
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    new_id UUID;
BEGIN
    -- FLOAT[] → VECTOR(768) 명시적 캐스팅으로 저장
    INSERT INTO documents (content, metadata, embedding)
    VALUES (
        p_content,
        p_metadata,
        p_embedding_array::vector(768)
    )
    RETURNING id INTO new_id;

    RETURN new_id;
END;
$$;

-- 함수 생성 확인
DO $$
BEGIN
    RAISE NOTICE '✅ insert_document_safe 함수 생성 완료';
    RAISE NOTICE '다음: hybrid_search_setup.sql 실행';
END $$;
