# Streamlit Community Cloud 배포

GitHub 저장소는 `darknagisa-lang/llmtest`, 시작 파일은 `app.py`입니다. ZIP을 내려받은 경우 압축을 푼 뒤 파일을 저장소 루트에 올립니다. `.streamlit/config.toml`을 포함하고 ZIP 파일 자체는 올리지 않습니다. 기존 저장소에 코드가 있으면 변경분을 먼저 확인하세요.

1. [Streamlit Community Cloud](https://share.streamlit.io/)에서 GitHub 계정을 연결하고 **Create app → Deploy a public app from GitHub** 등 GitHub 저장소에서 배포하는 메뉴로 이동합니다.
2. 저장소 `darknagisa-lang/llmtest`, 파일을 올린 브랜치(예: `main`), 파일 경로 `app.py`를 선택합니다.
3. **Advanced settings**에서 Python 3.12를 선택하고 **Secrets**에 아래 이름으로 실제 값을 입력합니다. GitHub에 키 파일을 업로드할 필요가 없습니다.

```toml
APP_DEPLOYMENT = "cloud"
OPENAI_API_KEY = "여기에 OpenAI 키 입력"
YOUTUBE_API_KEY = "여기에 YouTube 키 입력"
OPENAI_MODEL = "gpt-6-luna"
```

4. **Deploy**를 누른 뒤 설치 로그와 첫 화면을 확인합니다. 운영 키로 실행할 경우 앱을 비공개로 설정하고 사용할 계정만 초대하세요. 공개 접근을 허용하면 방문자가 앱의 API 할당량과 비용을 사용할 수 있습니다.

클라우드에서는 설정과 직접 등록한 제품 사양이 브라우저 세션 단위로 유지됩니다. 세션 종료 후에는 초기화될 수 있습니다. 기존 Windows 예약 작업은 클라우드에서 실행되지 않습니다. 08시 브리핑은 페이지 접근 또는 수동 갱신 시 로드하며, 주목할 만한 리뷰는 세션 내 비용·전송 범위를 확인한 뒤 수동으로 선정합니다.

- [Streamlit 앱 배포 및 Python 설정](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
- [Streamlit Secrets 관리](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
- [Streamlit 앱 공유 및 접근 권한](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app)
