# 🤖 중소기업 업무 자동화 RAG 솔루션

Google Drive 문서를 기반으로 질문에 답변하는 AI 업무 비서입니다.

## 🌟 주요 기능

- **📁 Google Drive 동기화**: 지정된 폴더의 문서를 자동으로 벡터 DB에 저장
- **💬 지능형 채팅**: Gemini 1.5 Flash (gemini-1.5-flash-latest)를 활용한 문서 기반 답변
- **📄 다양한 파일 지원**: PDF, DOCX, XLSX, TXT 파일 처리
- **🔍 의미 기반 검색**: Gemini Embeddings를 통한 정확한 문서 검색
- **📚 출처 표시**: 모든 답변에 참고 문서 출처 자동 표시

## 🛠️ 기술 스택

- **Frontend**: Streamlit
- **LLM**: Google Gemini 1.5 Flash (gemini-1.5-flash-latest)
- **Embeddings**: Google Gemini text-embedding-004 (768차원)
- **Vector DB**: Supabase pgvector
- **Framework**: LangChain
- **Cloud**: Google Drive API

## 🚀 로컬 실행

### 1. 사전 요구사항

- Python 3.12+
- Google Cloud Service Account (credentials.json)
- Supabase 계정
- Google API Key

### 2. 설치

```bash
# 저장소 클론
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO

# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt
```

### 3. 환경 변수 설정

`.env` 파일 생성:

```env
GOOGLE_API_KEY=your_google_api_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
GOOGLE_DRIVE_FOLDER_ID=your_folder_id
```

### 4. Supabase 설정

`setup_supabase.sql` 파일을 Supabase SQL Editor에서 실행:

```bash
# Supabase Dashboard > SQL Editor에서 실행
```

### 5. 실행

```bash
streamlit run app.py
```

브라우저에서 http://localhost:8501 접속

## ☁️ Streamlit Cloud 배포

자세한 배포 가이드는 [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)를 참고하세요.

### 간단 요약

1. GitHub에 코드 푸시
2. Streamlit Cloud에서 앱 생성
3. Secrets 설정 (secrets.toml.example 참고)
4. 배포 완료!

## 📖 사용 방법

### 1. Google Drive 동기화

1. 사이드바에서 Google Drive 폴더 ID 입력
2. "🔄 구글 드라이브 동기화" 버튼 클릭
3. 동기화 완료 대기

### 2. 질문하기

1. 채팅 입력창에 질문 입력
2. Gemini 1.5 Flash (gemini-1.5-flash-latest)가 문서를 기반으로 답변
3. 답변 끝에 참고 문서 출처 확인

## 📁 프로젝트 구조

```
01_RAG/
├── app.py                      # Streamlit UI
├── rag_module.py               # RAG 백엔드 로직
├── requirements.txt            # 패키지 의존성
├── .env                        # 환경 변수 (로컬)
├── .gitignore                  # Git 제외 파일
├── credentials.json            # Google Service Account (로컬)
├── setup_supabase.sql          # Supabase 초기 설정
├── fix_search_function.sql     # Supabase 검색 함수 수정
├── secrets.toml.example        # Streamlit Secrets 템플릿
├── DEPLOYMENT_GUIDE.md         # 배포 가이드
└── README.md                   # 프로젝트 문서
```

## 🔒 보안

- `.env`, `credentials.json`, `venv/` 등은 `.gitignore`에 포함
- Streamlit Cloud에서는 Secrets를 사용하여 안전하게 관리
- 보안 정보를 절대 GitHub에 커밋하지 마세요

## 🐛 문제 해결

### Google Drive API 오류

- Google Cloud Console에서 Drive API 활성화 확인
- Service Account 권한 확인
- credentials.json 형식 확인

### Supabase 연결 오류

- SUPABASE_URL과 SUPABASE_KEY 확인
- setup_supabase.sql 실행 여부 확인
- pgvector extension 활성화 확인

### 패키지 설치 오류

- Python 버전 확인 (3.12+ 권장)
- pip 업그레이드: `pip install --upgrade pip`
- 가상환경 재생성

## 📝 라이선스

MIT License

## 👥 기여

버그 리포트 및 기능 제안은 Issues에서 환영합니다!

## 📧 문의

프로젝트 관련 문의사항이 있으시면 Issues를 통해 연락주세요.

---

**Made with ❤️ using Streamlit + LangChain + Google Gemini + Supabase**
