# Streamlit Cloud 배포 가이드

## 📋 사전 준비

1. **GitHub 저장소 생성**
   - GitHub에 새 저장소 생성
   - 로컬 프로젝트를 GitHub에 푸시

2. **보안 파일 확인**
   - `.gitignore`가 제대로 설정되어 있는지 확인
   - `.env`, `credentials.json`, `venv/` 등이 절대 커밋되지 않도록 주의

---

## 🔐 Streamlit Cloud Secrets 설정

### 1. Streamlit Cloud에서 Secrets 설정 위치

1. Streamlit Cloud (https://share.streamlit.io) 접속
2. 배포된 앱 선택
3. **Settings** → **Secrets** 메뉴 클릭
4. 아래 내용을 복사하여 붙여넣기

### 2. secrets.toml 형식

Streamlit Cloud의 Secrets 입력창에 다음 내용을 **그대로** 붙여넣으세요:

```toml
# Google API Key for Gemini
GOOGLE_API_KEY = "AIzaSyDzLalwbUjA43n8QS5obAwncMGMjgvJdl0"

# Supabase Configuration
SUPABASE_URL = "https://zhkbgdlhioshtqqepvho.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inpoa2JnZGxoaW9zaHRxcWVwdmhvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjU1NDUwMzUsImV4cCI6MjA4MTEyMTAzNX0.5rfV1TfHC_BrDPCBy9K9JRrqcS2kgROPAcvnlvv5Fsw"

# Google Drive Folder ID
GOOGLE_DRIVE_FOLDER_ID = "1h2WP_3stWPuWZ1DfBdsxnsigT56ObfUu"

# Google Service Account Credentials (JSON을 한 줄로)
[google_credentials]
type = "service_account"
project_id = "YOUR_PROJECT_ID"
private_key_id = "YOUR_PRIVATE_KEY_ID"
private_key = "-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY\n-----END PRIVATE KEY-----\n"
client_email = "YOUR_SERVICE_ACCOUNT_EMAIL"
client_id = "YOUR_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "YOUR_CERT_URL"
```

---

## 📝 credentials.json 내용을 Secrets에 넣는 방법

### 옵션 1: TOML 딕셔너리 형식 (권장)

`credentials.json` 파일을 열어서 각 필드를 위의 `[google_credentials]` 섹션에 복사합니다.

**예시:**

만약 `credentials.json`이 이렇게 생겼다면:
```json
{
  "type": "service_account",
  "project_id": "my-project-123",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n",
  "client_email": "my-service@my-project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/..."
}
```

위의 `[google_credentials]` 섹션에 각 값을 복사하세요.

### 옵션 2: JSON 문자열 형식

또는 전체 JSON을 한 줄로 만들어 넣을 수도 있습니다:

```toml
GOOGLE_CREDENTIALS_JSON = '{"type":"service_account","project_id":"my-project-123",...}'
```

---

## 💻 코드에서 Secrets 읽기

### app.py와 rag_module.py 수정

Streamlit Cloud에서는 환경 변수를 `st.secrets`로 읽어야 합니다.

#### 1. app.py 수정

파일 상단에 다음 코드 추가:

```python
import os
import streamlit as st

# Streamlit Cloud에서는 st.secrets 사용
if "GOOGLE_API_KEY" in st.secrets:
    os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
    os.environ["SUPABASE_URL"] = st.secrets["SUPABASE_URL"]
    os.environ["SUPABASE_KEY"] = st.secrets["SUPABASE_KEY"]
    os.environ["GOOGLE_DRIVE_FOLDER_ID"] = st.secrets["GOOGLE_DRIVE_FOLDER_ID"]
```

#### 2. rag_module.py에서 credentials 처리

Google Drive 인증 함수 수정:

```python
def authenticate_google_drive(credentials_path: str = "credentials.json"):
    """
    Google Drive API 인증
    """
    try:
        # Streamlit Cloud에서는 st.secrets 사용
        try:
            import streamlit as st
            if "google_credentials" in st.secrets:
                # Secrets에서 credentials 가져오기
                credentials_dict = dict(st.secrets["google_credentials"])
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_dict,
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
            else:
                # 로컬에서는 파일 사용
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_path,
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
        except ImportError:
            # Streamlit이 없으면 로컬 파일 사용
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )

        service = build('drive', 'v3', credentials=credentials)
        print(f"[OK] Google Drive 인증 완료")
        return service
    except Exception as e:
        print(f"[ERROR] Google Drive 인증 실패: {str(e)}")
        raise
```

---

## 🚀 배포 단계

### 1. GitHub에 푸시

```bash
# Git 초기화 (아직 안 했다면)
git init
git add .
git commit -m "Initial commit: RAG solution"

# GitHub 저장소와 연결
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

### 2. Streamlit Cloud 배포

1. https://share.streamlit.io 접속
2. **New app** 클릭
3. GitHub 저장소 선택
4. Branch: `main`
5. Main file path: `app.py`
6. **Advanced settings** → **Python version**: 3.12
7. **Deploy!** 클릭

### 3. Secrets 설정

1. 배포 완료 후 **Settings** → **Secrets** 이동
2. 위의 `secrets.toml` 내용 붙여넣기
3. **Save** 클릭
4. 앱이 자동으로 재시작됨

---

## ⚠️ 주의사항

### 보안 체크리스트

- [ ] `.env` 파일이 `.gitignore`에 포함되어 있는지 확인
- [ ] `credentials.json`이 `.gitignore`에 포함되어 있는지 확인
- [ ] GitHub 저장소에 보안 정보가 노출되지 않았는지 확인
- [ ] Streamlit Cloud Secrets에 모든 키가 올바르게 입력되었는지 확인

### 보안 정보가 커밋된 경우

만약 실수로 보안 정보를 커밋했다면:

```bash
# 히스토리에서 파일 완전 제거
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch .env credentials.json" \
  --prune-empty --tag-name-filter cat -- --all

# 강제 푸시
git push origin --force --all
```

그 후 **반드시** 노출된 API 키를 재발급 받으세요!

---

## 🔧 문제 해결

### 앱이 시작되지 않는 경우

1. **Logs** 확인: Streamlit Cloud에서 에러 로그 확인
2. **Secrets 형식**: TOML 형식이 올바른지 확인 (따옴표, 등호 등)
3. **Python 버전**: Python 3.12 설정 확인
4. **requirements.txt**: 모든 패키지가 올바르게 명시되어 있는지 확인

### Google Drive API 오류

1. Google Cloud Console에서 API 활성화 확인
2. Service Account 권한 확인
3. credentials.json의 private_key에 `\n`이 올바르게 포함되어 있는지 확인

---

## 📚 참고 자료

- [Streamlit Cloud Documentation](https://docs.streamlit.io/streamlit-community-cloud)
- [Streamlit Secrets Management](https://docs.streamlit.io/streamlit-community-cloud/deploy-your-app/secrets-management)
- [Google Drive API](https://developers.google.com/drive/api/guides/about-sdk)
- [Supabase Documentation](https://supabase.com/docs)

---

## ✅ 배포 완료 확인

배포가 완료되면:

1. Streamlit Cloud URL 접속
2. 사이드바에서 "구글 드라이브 동기화" 클릭
3. 정상적으로 파일이 동기화되는지 확인
4. 채팅창에서 질문 테스트

**축하합니다! 🎉 RAG 솔루션이 성공적으로 배포되었습니다!**
