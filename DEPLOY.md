# 배포 가이드 — GitHub 공개 저장소 + Railway 온라인 데모

이 문서는 (1) 소스를 **GitHub 공개 저장소**에 올리고, (2) **Railway**에 배포해
심사위원이 URL로 접속·로그인 체험할 수 있게 하는 단계별 안내입니다.
계정 로그인이 필요한 단계는 **본인이 직접** 수행합니다.

---

## 1. GitHub 공개 저장소에 올리기

### 방법 A — 명령줄(git)

```bash
# 프로젝트 폴더에서
git init
git add .
git commit -m "IQC dashboard: 내부정도관리 종합검토·전자서명 웹 대시보드"
git branch -M main
# GitHub에서 새 '공개(Public)' 저장소를 먼저 만든 뒤, 그 주소로:
git remote add origin https://github.com/<본인아이디>/iqc-dashboard.git
git push -u origin main
```

### 방법 B — GitHub 웹 업로드
GitHub → **New repository**(Public) 생성 → "uploading an existing file" →
이 폴더의 파일 전체를 드래그 업로드 → Commit.

> `.gitignore`가 `venv/`, `instance/*.sqlite3`, `secret_key.txt`, `__pycache__/`를
> 제외하므로 **가상환경·DB·세션키는 올라가지 않습니다**(정상). 소스·폰트·샘플만 공개됩니다.

공개 후, 지원서의 GitHub 칸에 `https://github.com/<본인아이디>/iqc-dashboard` 를 기재하세요.

---

## 2. Railway 온라인 배포

1. https://railway.app 로그인 → **New Project** → **Deploy from GitHub repo** → 위 저장소 선택.
2. Railway가 `railway.json` / `Procfile` / `.python-version`을 읽어 자동으로 빌드·실행합니다.
   - 빌드: Nixpacks(Python 3.12) + `pip install -r requirements.txt`
   - 실행: `python serve.py` (플랫폼이 주입하는 `PORT`를 자동 사용, `0.0.0.0` 바인딩)
   - **최초 실행 시 데모 시드가 자동 적재**되어 바로 로그인 가능합니다.
3. **Settings → Networking → Generate Domain** 으로 공개 도메인을 만듭니다.
   생성된 `https://<프로젝트>.up.railway.app` 주소로 접속 → `admin/admin123` 등으로 로그인.
4. (권장) **Variables** 에 아래 환경변수를 추가하면 재배포에도 로그인 세션이 유지됩니다.
   - `IQC_SECRET_KEY` = (임의의 긴 무작위 문자열)

### 데모 데이터 영구 보존(선택)
무료 플랜은 재배포 시 컨테이너 파일이 초기화되어 서명·검토 기록이 사라질 수 있습니다.
데모 목적이면 자동 재적재로 충분하지만, 영구 보존이 필요하면 둘 중 하나:

- **Railway Volume**: 볼륨을 `/data`에 마운트하고 변수 `IQC_DATABASE_URI=sqlite:////data/iqc.sqlite3` 설정.
- **PostgreSQL**: Railway에서 Postgres 추가 후, 제공되는 `DATABASE_URL`을 변수
  `IQC_DATABASE_URI` 로 연결(드라이버 `psycopg[binary]` 추가 필요).

> 심사 제출용이라면 기본(자동 재적재)만으로 충분합니다. 위 영구 보존은 실제 운영 시 옵션입니다.

---

## 3. 로컬(검사실 인트라넷) 실행
`README.md` 3장 또는 `서버시작.bat` 참고. 클라우드와 동일 코드가 로컬에서도 그대로 동작합니다.
