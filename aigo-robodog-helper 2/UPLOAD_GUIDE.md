# GitHub 웹사이트 수동 업로드

## 1. 준비한 ZIP 압축 풀기

`AIGO_키오스크_복약알림_GitHub업로드.zip`을 풀면 `aigo-robodog-helper` 폴더가 나옵니다. 그 안에 `main.py`, `README.md`, `web`, `data`, `tests` 등이 있습니다.

**ZIP 파일 자체를 업로드하지 않습니다. 압축을 푼 소스 파일을 올립니다.**

## 2. 저장소 만들기

1. GitHub에 로그인합니다.
2. 오른쪽 위 `+ → New repository`를 선택합니다.
3. 이름은 예를 들어 `aigo-robodog-helper`로 정합니다.
4. 공개하려면 `Public`, 본인·초대한 사람만 보려면 `Private`를 선택합니다.
5. 이번 묶음에 README가 있으므로 초기 README 생성은 생략할 수 있습니다.
6. `Create repository`를 누릅니다.

이미 올릴 저장소가 있다면 새로 만들지 않고 그 저장소에서 다음 단계로 진행합니다.

## 3. 파일과 폴더 업로드

1. 새 저장소 화면에서 `uploading an existing file` 링크를 누릅니다. 파일이 있는 저장소에서는 `Add file → Upload files`입니다.
2. 압축을 푼 **`aigo-robodog-helper` 폴더 안의 내용물**을 선택합니다.
3. `main.py` 등 파일과 `web`, `data`, `tests`, `references` 폴더를 업로드 영역으로 끌어 놓습니다. 폴더 구조가 그대로 유지되어야 합니다.
4. `.gitignore`도 포함합니다. Finder에서 보이지 않으면 `Command + Shift + .`로 숨김 파일을 표시할 수 있습니다. Windows 탐색기에서는 숨긴 항목 표시를 켭니다.
5. 업로드 목록에서 `main.py`와 `web/index.html`이 있는지 확인합니다. 파일이 `web` 폴더 밖으로 납작하게 풀리면 안 됩니다.

처음 업로드가 끝난 저장소 최상위에 `main.py`와 `README.md`가 보이면 됩니다. 바깥의 `aigo-robodog-helper` 폴더까지 통째로 드래그하면 한 단계 더 들어간 폴더에 저장될 수 있으니, 최상위가 되도록 **폴더 안의 파일·하위 폴더**를 올리는 방식을 사용합니다.

## 4. 저장 완료

1. 커밋 메시지에 `Add AIGO kiosk and medication reminder`를 입력합니다.
2. 본인의 새 빈 저장소라면 기본 브랜치에 저장합니다. 기존 공동 작업 저장소라면 새 브랜치로 제안할 수 있습니다.
3. `Commit changes`를 누릅니다. 화면에 따라 `Propose changes`로 표시될 수도 있습니다.
4. 저장소로 돌아와 `web/index.html`, `web/app.js`, `medication.py`, `robot_controller.py`를 확인합니다.

## 올린 뒤 실행하는 법

GitHub에서 `Code → Download ZIP`으로 내려받아 압축을 풀고 Thonny에서 `main.py`를 F5로 실행합니다.

이 앱은 Python 로컬 서버와 장치 연결을 사용하므로 GitHub Pages에 HTML만 게시해서 전체 기능을 실행할 수는 없습니다. HTML이 GitHub에서 코드로 보이는 것은 정상입니다.

## 다음에 수정한 파일을 다시 올릴 때

같은 경로에 수정한 파일을 업로드하고 커밋합니다. `web/index.html`을 바꿨다면 `web` 폴더 안에 같은 이름으로 올라가야 합니다. 새 이미지나 JS/CSS를 추가했다면 함께 업로드합니다. 로컬 실행으로 생긴 복약 예약·학습 결과 파일은 업로드에서 제외합니다.

## 공식 안내

- 파일·폴더 업로드: https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository
- 브라우저 업로드는 파일당 25 MiB, 한 번에 최대 100개입니다. 이번 묶음은 이 범위 안에 맞췄습니다.
- GitHub Pages의 정적 호스팅 범위: https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
