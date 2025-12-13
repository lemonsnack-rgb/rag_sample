import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 1. 인증 준비 (credentials.json 파일이 같은 폴더에 있어야 함)
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'

try:
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)

    # 2. 쿼리 없이 그냥 보이는 거 다 가져오기 (Trash 된 거 빼고)
    # 로봇 계정은 공유받은 파일만 볼 수 있으므로, 여기서 안 보이면 공유가 안 된 것임.
    results = service.files().list(
        pageSize=50, 
        fields="nextPageToken, files(id, name, mimeType, parents)",
        q="trashed=false" 
    ).execute()
    
    items = results.get('files', [])

    print(f"=== 로봇(서비스 계정)이 볼 수 있는 파일 총 {len(items)}개 ===")
    
    if not items:
        print("❌ 아무 파일도 안 보입니다! '공유' 설정이 안 된 것 같습니다.")
        print("   -> 구글 드라이브 폴더에서 서비스 계정 이메일을 다시 초대해주세요.")
    else:
        for item in items:
            print(f"------------------------------------------------")
            print(f"📄 파일명: {item['name']}")
            print(f"🆔 파일ID: {item['id']}")
            print(f"📂 부모폴더ID: {item['parents']}")
            print(f"🏷️ 타입(MimeType): {item['mimeType']}")
            
            # PDF인지 확인
            if 'pdf' in item['mimeType']:
                print("   ✅ PDF 파일입니다. (코드에서 이걸 읽도록 설정해야 함)")
            elif 'folder' in item['mimeType']:
                 print("   📁 폴더입니다.")
            else:
                 print("   📝 기타 파일입니다.")

except Exception as e:
    print(f"🚫 에러 발생: {e}")