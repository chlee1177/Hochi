# 이미지 인식·요약 — Android

Kotlin 네이티브 앱입니다. Android 8.0(API 26) 이상을 지원합니다. 갤러리에서 PNG/JPEG/WebP/GIF 이미지(최대 8 MiB)를 선택하고 전송에 동의하면 한국어 설명·주요 요소·핵심 요약·불확실성을 받습니다. 카메라 직접 촬영과 오프라인 인식은 아직 없습니다.

## 실행

1. Android Studio에서 `android` 폴더를 엽니다. JDK 17, Android SDK 35를 사용합니다. 프로젝트에 Gradle wrapper가 포함됩니다.
2. Python 3.12+가 있는 개발 컴퓨터에서 `HOCHI_AI_KEY`를 안전하게 환경 변수로 설정하고 `python backend/server.py`를 실행합니다.
3. Android 에뮬레이터에서 앱을 실행합니다. 기본 서버 주소 `http://10.0.2.2:8101`은 에뮬레이터에서 개발 컴퓨터를 가리킵니다. 이 주소의 HTTP 연결은 디버그 빌드에만 허용합니다.
4. 실제 기기에서는 접근 가능한 **HTTPS 분석 서버** 주소를 입력해야 합니다. 포함된 Python 서버는 로컬 개발용이며 실제 서비스를 위해 인증·요청 제한·HTTPS와 안전한 서버 배포 구성이 필요합니다. 공개 서버는 이번에 배포하지 않았습니다.

실제 분석에는 OpenAI 키가 필요합니다. 키가 없으면 오류를 명확히 표시하며 분석 결과를 만들어내지 않습니다. 이미지가 OpenAI API로 전송되고 Python 서버에서는 디스크에 저장하지 않습니다. 키를 APK에 넣지 마세요.

## 빌드

Windows: `android` 폴더에서 `gradlew.bat assembleDebug lintDebug`.
클라우드: 저장소 루트에서 `python scripts/build_android.py`.

APK는 `android/app/build/outputs/apk/debug/app-debug.apk`에 생성됩니다. 이 파일은 테스트용 디버그 APK이며 스토어 출시용으로 서명한 APK가 아닙니다.

후속 후보: 카메라 촬영, OCR 모드, 결과 공유, 여러 이미지 비교, 로컬 모델, 서버 인증.
