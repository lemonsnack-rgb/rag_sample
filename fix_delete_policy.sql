-- Supabase에서 실행: DB 삭제 권한 추가

-- 기존 DELETE 정책이 있다면 삭제
DROP POLICY IF EXISTS "Service role can delete documents" ON public.documents;
DROP POLICY IF EXISTS "Authenticated users can delete documents" ON public.documents;

-- 모든 사용자가 삭제 가능하도록 정책 생성 (임시)
CREATE POLICY "Anyone can delete documents"
ON public.documents
FOR DELETE
USING (true);

-- 또는 인증된 사용자만 삭제 가능하도록 (권장)
-- CREATE POLICY "Authenticated users can delete documents"
-- ON public.documents
-- FOR DELETE
-- USING (auth.role() = 'authenticated');

-- UPDATE 정책도 추가 (필요시)
DROP POLICY IF EXISTS "Anyone can update documents" ON public.documents;
CREATE POLICY "Anyone can update documents"
ON public.documents
FOR UPDATE
USING (true);
