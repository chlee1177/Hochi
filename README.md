# Hochi — 세 가지 프로젝트

요청한 세 프로젝트의 실행 가능한 초기 버전입니다. 하나의 저장소 안에서 폴더별로 관리합니다.

| 프로젝트 | 플랫폼 | 시작점 |
| --- | --- | --- |
| 이미지 인식·요약 | Kotlin 안드로이드 앱 + Python 분석 서버 | `image-summary/android`를 Android Studio에서 열기 |
| AI 파일 정리 | Python Windows 데스크톱 앱 (Tkinter) | `file-organizer/start.bat` 실행 |
| 스페이스 머셔너리 | Godot 4.6 기반 2D PC 게임 | `space-mercenary/project.godot`를 Godot에서 열고 F5 실행 |

각 폴더 README에 상세 실행 방법이 있습니다. 이미지 분석에는 AI 키 연결이 필요합니다. 파일 정리는 OpenAI 또는 API 키가 필요 없는 Ollama 로컬 모델을 선택할 수 있습니다. 게임은 키 없이 실행됩니다. 파일 정리는 지정 폴더의 파일명과 지원 내용을 AI로 분석한 뒤 검토한 원본을 분류 폴더로 이동합니다.

## AI 연결

OpenAI 모드는 Responses API를 사용합니다. 이미지 분석 서버 또는 Windows 프로그램의 실행 환경에 `HOCHI_AI_KEY`를 설정하세요. 키는 앱 소스·안드로이드 APK·채팅·Git에 넣지 않습니다. `.env`는 자동 로드되지 않습니다. 모델은 `HOCHI_AI_MODEL`로 지정하며 기본값은 `gpt-4.1-mini`입니다. API 사용료가 발생할 수 있습니다.

파일 정리 앱의 Ollama 모드는 `ollama pull qwen3:14b`로 로컬 모델을 설치한 뒤 분석 설정에서 선택합니다. 서버 기본 주소는 `http://127.0.0.1:11434`이며 API 키 없이 사용할 수 있습니다. 자세한 설치 방법은 `file-organizer/README.md`를 확인하세요.

안드로이드 앱은 키를 보유하지 않고 분석 서버로 이미지를 보냅니다. Windows 파일 정리 앱은 로컬 민감 검사 후 허용된 파일명·상대 경로와 지원 내용을 전송합니다. 민감 후보와 로컬 검사 불가 이미지는 검토 대기로 두며 개별 전송 승인과 이동 승인을 구분합니다. AI가 최대 3단계 분류·요약·태그를 제안하고, 사용자가 수정·선택하여 이동할 수 있습니다. 로컬 검색·중복 검사·작업 기록도 지원합니다. 지원 범위와 복구 방식은 file-organizer/README.md를 확인하세요.

## 클라우드 개발 환경

Python 3.12+, JDK 17, Android SDK 35, Gradle 8.13, Godot 4.6이 필요합니다. 이 환경에서는 다음 명령을 사용합니다.

```sh
cd /workspace/Hochi
python scripts/setup_android.py
python scripts/build_android.py
python -m unittest discover -s tests -v
```

게임 검증 시 쓰기 가능한 캐시 경로를 지정합니다.

```sh
export XDG_DATA_HOME=/workspace/.tools/xdg-data
export XDG_CONFIG_HOME=/workspace/.tools/xdg-config
export XDG_CACHE_HOME=/workspace/.tools/xdg-cache
godot --headless --path space-mercenary --script test_campaign.gd
```

APK 위치: `image-summary/android/app/build/outputs/apk/debug/app-debug.apk`.
GUI 통합 확인: 디스플레이가 있는 환경에서 `python tests/smoke_desktop.py`.

클라우드에서의 빌드·테스트는 실제 휴대폰 및 Windows에서의 실행 검증을 대신하지 않습니다. GitHub 원격 업로드와 환경 게시도 별도입니다.
