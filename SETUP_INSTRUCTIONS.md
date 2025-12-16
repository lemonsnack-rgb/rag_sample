# RAG 검색 품질 개선 - 설정 가이드

## 🚨 중요: 반드시 순서대로 진행하세요

### 1단계: Supabase 초기화 (SQL Editor에서 실행)

Supabase 대시보드 → SQL Editor → New Query 생성 후 아래 순서대로 실행:

#### A. 기본 설정 (reset_supabase_complete.sql)
```sql
-- 이미 존재하는 파일 실행
-- reset_supabase_complete.sql의 내용 복사 & 실행
```

#### B. RPC 함수 추가 (필수!)
```sql
-- 임베딩 저장 함수 (FLOAT[] → VECTOR(768) 변환)
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
```

#### C. 하이브리드 검색 설정 (hybrid_search_setup.sql)
```sql
-- 이미 존재하는 파일 실행
-- hybrid_search_setup.sql의 내용 복사 & 실행
```

### 2단계: 코드 수정 완료 확인

- ✅ rag_module.py 수정됨
- ✅ app.py 수정됨
- ✅ 청크 크기 800자로 조정됨

### 3단계: Streamlit에서 재색인

1. http://localhost:8501 접속
2. 사이드바 → 관리자 기능
3. "전체 재색인" 체크
4. "문서 동기화" 클릭
5. 모든 파일이 에러 없이 색인되는지 확인

### 4단계: 테스트

#### 테스트 쿼리 1: 정확한 키워드
```
새물리 논문 투고 규정은?
```
**기대 결과:**
- Hybrid Score: 0.85+
- "새물리 논문투고 규정(2024.04).pdf" 상위 3개 안에 표시

#### 테스트 쿼리 2: 유사 키워드
```
물리학 논문 투고 규정은?
```
**기대 결과:**
- Hybrid Score: 0.70+
- "새물리 논문투고 규정(2024.04).pdf" 상위 5개 안에 표시
- 키워드 매칭: "논문", "투고", "규정"

---

## 문제 발생 시 체크리스트

- [ ] Supabase SQL Editor에서 3개 SQL 모두 실행했는가?
- [ ] `insert_document_safe` 함수가 생성되었는가?
- [ ] `hybrid_search_documents` 함수가 생성되었는가?
- [ ] DB를 완전히 삭제하고 재색인했는가?
- [ ] 색인 중 에러가 발생하지 않았는가?

## 기술적 변경 내역

### 해결된 문제
1. **임베딩 TEXT 저장 → VECTOR(768) 저장**
   - Before: 9,514차원 (TEXT)
   - After: 768차원 (VECTOR)

2. **단순 벡터 검색 → 하이브리드 검색**
   - 벡터 유사도 60% + 키워드 매칭 40%
   - 정확한 단어가 있으면 상위 노출 보장

3. **청크 크기 최적화**
   - Before: 2,000자 (키워드 희석)
   - After: 800자 (키워드 밀도 증가)

4. **다양성 필터**
   - 파일당 최대 3개 청크로 제한
   - 특정 문서 독점 방지
