# Streamlit Cloud 배포 체크리스트

## 현재 상태
- ✅ GitHub에 최신 코드 배포 완료 (커밋: `a0884ce`)
- ✅ 로컬 DB 검증 완료 (차원=768, 유사도 정상)
- ❌ Streamlit Cloud에서 여전히 평균 관련도 2.49 표시 중

## 배포 완료를 위한 필수 단계

### 1단계: Supabase RPC 함수 생성 (가장 중요!)

**Supabase Dashboard → SQL Editor → New Query**에서 다음 SQL 실행:

```sql
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
        p_embedding_array::vector(768)  -- ⭐ 핵심: FLOAT[]를 VECTOR(768)로 명시적 변환
    )
    RETURNING id INTO new_id;

    RETURN new_id;
END;
$$;
```

**왜 필요한가?**: 이 함수가 없으면 Python 클라이언트가 임베딩을 TEXT로 저장하여 차원이 9,486으로 깨집니다.

### 2단계: Supabase DB 초기화

**Supabase Dashboard → SQL Editor → New Query**에서 `reset_supabase_complete.sql` 파일 내용 전체를 복사하여 실행:

```sql
-- 1. 기존 테이블 삭제 (cascade)
DROP TABLE IF EXISTS documents CASCADE;

-- 2. 새 테이블 생성
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    metadata JSONB,
    embedding VECTOR(768),  -- ⭐ 768차원 벡터
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 인덱스 생성 (벡터 검색 성능 향상)
CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- 4. RLS 정책 설정
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Enable read access for all users" ON documents
    FOR SELECT USING (true);

CREATE POLICY "Enable insert for all users" ON documents
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Enable update for all users" ON documents
    FOR UPDATE USING (true);

CREATE POLICY "Enable delete for all users" ON documents
    FOR DELETE USING (true);

-- 5. 검색 함수 생성
CREATE OR REPLACE FUNCTION match_documents(
    query_embedding VECTOR(768),
    match_threshold FLOAT,
    match_count INT
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
```

**주의**: 이 작업은 기존 데이터를 모두 삭제합니다!

### 3단계: Streamlit Cloud 앱 재시작

1. **Streamlit Cloud Dashboard** 접속: https://share.streamlit.io/
2. 앱 찾기: `ragsample-hu7mpmtjx6ydd2ruzwpynh`
3. **⋮ (메뉴)** 클릭 → **Reboot app** 선택
4. **2-3분 대기** (앱이 새 코드로 재시작)

### 4단계: 전체 재색인 실행

1. **Streamlit Cloud 앱 접속**: https://ragsample-hu7mpmtjx6ydd2ruzwpynh.streamlit.app/
2. **사이드바 → 관리자 기능** 펼치기
3. **✅ 전체 재색인 (기존 문서 삭제 후 다시 색인)** 체크
4. **"문서 동기화"** 버튼 클릭
5. **진행 상황 관찰**: 24개 문서가 모두 색인될 때까지 대기

### 5단계: 검증

다음 쿼리로 테스트:

```
인용문헌 기재 방식은?
```

**기대 결과**:
- ✅ 평균 관련도: **0.3 ~ 0.8** 범위 (정상)
- ❌ 평균 관련도: **2.49** (실패 - 1단계부터 다시)

**추가 검증 쿼리**:
```
논문 심사 규정은?
```

**기대 결과**: "논문 투고" 문서가 아닌 **"논문 심사" 관련 문서**가 최상위에 표시됨

## 문제 해결

### 문제: 여전히 평균 관련도 2.49가 나옴

**원인**: 1단계의 `insert_document_safe` 함수가 생성되지 않았을 가능성

**해결**:
1. Supabase → SQL Editor → Functions 탭에서 `insert_document_safe` 함수 존재 확인
2. 없으면 1단계 SQL 다시 실행
3. Supabase → SQL Editor에서 검증 쿼리 실행:
   ```sql
   SELECT vector_dims(embedding) as dimension
   FROM documents
   LIMIT 5;
   ```
   - 결과가 768이면 정상
   - 결과가 없거나 에러면 2단계(DB 초기화) 다시 실행

### 문제: 재색인 중 API 키 에러

**원인**: Streamlit Cloud에 환경 변수가 설정되지 않음

**해결**:
1. Streamlit Cloud Dashboard → 앱 설정 → Secrets
2. 다음 내용 추가:
   ```toml
   GOOGLE_API_KEY = "AIzaSyCUi0tOJ3U36cAdafjiAoy7Y2Zz-t-lOrg"
   SUPABASE_URL = "https://zhkbgdlhioshtqqepvho.supabase.co"
   SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inpoa2JnZGxoaW9zaHRxcWVwdmhvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjU1NDUwMzUsImV4cCI6MjA4MTEyMTAzNX0.5rfV1TfHC_BrDPCBy9K9JRrqcS2kgROPAcvnlvv5Fsw"
   GOOGLE_DRIVE_FOLDER_ID = "1h2WP_3stWPuWZ1DfBdsxnsigT56ObfUu"
   ```
3. **Save** 클릭 (자동으로 앱 재시작)

### 문제: Google Drive 동기화 실패

**임시 해결책**: 관리자 기능에서 폴더 ID를 직접 입력
1. 사이드바 → 관리자 기능
2. **Google Drive 폴더 ID 설정** 필드에 `1h2WP_3stWPuWZ1DfBdsxnsigT56ObfUu` 입력
3. "문서 동기화" 클릭

## 주요 코드 변경 사항 (이미 GitHub에 배포됨)

### ✅ RPC 함수 사용 (rag_module.py:456-466)
```python
# 🔧 최종 수정: RPC 함수로 안전한 삽입
supabase_client.rpc("insert_document_safe", {
    "p_content": doc.page_content,
    "p_metadata": doc.metadata,
    "p_embedding_array": embedding_vector  # Python list → FLOAT[] → VECTOR(768)
}).execute()
```

### ✅ 원본 쿼리 가중치 3배 (app.py:344-368)
```python
# 원본 쿼리(idx=0)는 가중치 3배
weight_multiplier = 3.0 if idx == 0 else 1.0
weighted_info['score'] = i['score'] * weight_multiplier
```

### ✅ 청크 크기 증가 (rag_module.py:191-198)
- XLSX: 500 → 1500자
- PPTX: 1500 → 2000자
- 기타: 1000 → 2000자

### ✅ 검색 임계값 완화 (rag_module.py:540-557)
- 1차 검색: 0.5 → 0.3
- 2차 검색: 0.15 → 0.1
- 최소 결과: 3개 → 5개

### ✅ 섹션 태그 제거 (rag_module.py:438-442)
```python
# 순수 내용만 임베딩 (섹션 태그 없음)
docs.append(Document(
    page_content=sub_chunk,  # [제88조(...)] 같은 태그 제거됨
    metadata={"section": section_name, ...}
))
```

## 완료 후 확인

배포가 성공하면:
- ✅ 검색 결과에 관련 문서가 정확히 표시됨
- ✅ 평균 관련도가 0.3 ~ 0.8 범위
- ✅ "논문 심사 규정" 검색 시 정확한 문서 반환
- ✅ 질의어가 포함된 청크가 상위에 표시됨

## 다음 작업 (검색 품질 확인 후)

검색이 정상적으로 작동하면 **다중 출처 인용 개선** 작업 진행:
- [ ] `format_docs_with_sources()` 함수 구현
- [ ] 연속된 청크를 출처 파일별로 그룹화
- [ ] 답변에 `📄 **[출처: filename.pdf]**` 형식으로 출처 표시
- [ ] LLM 프롬프트에 출처 인용 지시 추가

---

**작성 일시**: 2025-12-15
**최신 커밋**: a0884ce - Critical Fix: RPC 함수로 VECTOR(768) 명시적 캐스팅
