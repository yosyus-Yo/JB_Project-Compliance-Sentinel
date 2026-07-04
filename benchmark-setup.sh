#!/usr/bin/env bash
# benchmark-setup.sh v2 — aieev 컨테이너 JB + AC 설치 (vLLM 분리)
#
# 사용:
#   cd /workspace/jb-benchmark/JB_Project-Compliance-Sentinel
#   bash benchmark-setup.sh           # 기본: JB + AC base만 (5분 내)
#   bash benchmark-setup.sh --with-vllm  # vLLM까지 (10-15분 추가)
#
# v2 변경:
# - vLLM 기본 제외 (느려서 멈춘 것처럼 보임). 별도 옵션으로 분리.
# - set -e 제거 — 한 단계 실패해도 계속 진행 (warn만 출력)
# - pip dependency conflict ERROR 무시 (warning일 뿐)
# - 각 단계별 명확한 진행 표시 + tail로 마지막 줄만

# set 옵션 의도적으로 완화 — 에러 발생해도 진행
set -u  # 미정의 변수만 차단

# ─── 옵션 파싱 ───────────────────────────────────────────────
WITH_VLLM=0
for arg in "$@"; do
  case "$arg" in
    --with-vllm) WITH_VLLM=1 ;;
  esac
done

# ─── 색상 ────────────────────────────────────────────────────
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; B='\033[0;34m'; N='\033[0m'
log()  { echo -e "${G}[setup]${N} $1"; }
step() { echo -e "${B}[$1]${N} $2"; }
warn() { echo -e "${Y}[warn]${N} $1"; }
err()  { echo -e "${R}[error]${N} $1" >&2; }

# ─── 경로 ────────────────────────────────────────────────────
BENCH_ROOT="${BENCH_ROOT:-/workspace/jb-benchmark}"
JB_DIR="$BENCH_ROOT/JB_Project-Compliance-Sentinel"
AC_DIR="$BENCH_ROOT/AgentCompiler"
VENV_DIR="$BENCH_ROOT/venv"
AC_BRANCH="q5-real-wiring-2026-05-20"

# pip 출력 억제 + cache 비활성 (jovyan 권한 문제 회피)
PIP_FLAGS="--no-cache-dir --disable-pip-version-check"

if [ ! -f "$JB_DIR/pyproject.toml" ]; then
  err "JB pyproject.toml 못 찾음: $JB_DIR"
  exit 1
fi

echo "=========================================="
echo "  benchmark-setup.sh v2"
echo "  WITH_VLLM=$WITH_VLLM (vLLM은 별도)"
echo "=========================================="

# ─── 1. AgentCompiler clone ─────────────────────────────────
step 1/6 "AgentCompiler"
if [ ! -d "$AC_DIR/.git" ]; then
  log "clone 시작..."
  cd "$BENCH_ROOT"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    gh repo clone Aithor-organization/AgentCompiler 2>&1 | tail -3
  else
    git clone https://github.com/Aithor-organization/AgentCompiler.git 2>&1 | tail -3
  fi
fi

if [ -d "$AC_DIR/.git" ]; then
  cd "$AC_DIR"
  git fetch origin --quiet 2>&1 | tail -2 || warn "git fetch 실패 (계속 진행)"
  git checkout "$AC_BRANCH" 2>&1 | tail -2 || warn "checkout 실패"
  log "AC: $(git log --oneline -1 2>/dev/null || echo unknown)"
else
  err "AgentCompiler clone 실패. 수동 진행 필요."
  exit 1
fi

# ─── 2. venv ────────────────────────────────────────────────
step 2/6 "venv 생성/활성화"
if [ ! -d "$VENV_DIR" ]; then
  cd "$BENCH_ROOT" && python3 -m venv venv
  log "venv 새로 생성: $VENV_DIR"
else
  log "venv 이미 있음 (재사용)"
fi

source "$VENV_DIR/bin/activate"
log "Python: $(python3 --version)"

log "pip 업그레이드..."
pip install $PIP_FLAGS --upgrade pip wheel setuptools 2>&1 | tail -3

# ─── 3. JB 설치 ──────────────────────────────────────────────
step 3/6 "JB 설치 (extras: llm,langgraph,telemetry) — 약 1-2분"
cd "$JB_DIR"
pip install $PIP_FLAGS -e ".[llm,langgraph,telemetry]" 2>&1 | tail -5

# JB import 확인
if python3 -c "import compliance_sentinel" 2>/dev/null; then
  log "JB import ✅"
else
  warn "JB import 실패 — PYTHONPATH=src/ 시도"
  export PYTHONPATH="$JB_DIR/src:${PYTHONPATH:-}"
fi

# ─── 4. AgentCompiler 설치 (base만) ─────────────────────────
step 4/6 "AgentCompiler 설치 (base, no GPU) — 약 30초"
cd "$AC_DIR"
pip install $PIP_FLAGS -e . 2>&1 | tail -5

python3 -c "import agentcompiler; print(f'  AC ✅ {agentcompiler.__file__}')" \
  || warn "AC import 실패"

# ─── 5. 추가 도구 ────────────────────────────────────────────
step 5/6 "openai + huggingface-hub"
pip install $PIP_FLAGS openai huggingface-hub 2>&1 | tail -3

python3 -c "import openai; print(f'  openai ✅ v{openai.__version__}')" || warn "openai import 실패"

# ─── 6. (옵션) vLLM 설치 ────────────────────────────────────
if [ "$WITH_VLLM" -eq 1 ]; then
  step 6/6 "vLLM 설치 (10-15분 소요, CUDA torch 컴파일) ⏳"
  log "vLLM은 무거운 패키지입니다. 인내심을 가지세요..."
  log "진행 상황: tail -f /tmp/vllm-install.log (별도 터미널)"

  pip install $PIP_FLAGS vllm > /tmp/vllm-install.log 2>&1 &
  PIP_PID=$!

  # 30초마다 진행 상황 출력
  while kill -0 $PIP_PID 2>/dev/null; do
    sleep 30
    LAST_LINE=$(tail -1 /tmp/vllm-install.log 2>/dev/null | head -c 100)
    log "vLLM 설치 진행 중... ($(date +%H:%M:%S)) — last: $LAST_LINE"
  done

  wait $PIP_PID
  VLLM_EXIT=$?
  if [ "$VLLM_EXIT" -eq 0 ]; then
    python3 -c "import vllm; print(f'  vllm ✅ v{vllm.__version__}')" \
      || warn "vLLM import 실패 (재실행 필요)"
  else
    err "vLLM 설치 실패 (exit $VLLM_EXIT)"
    warn "로그 확인: cat /tmp/vllm-install.log | tail -50"
  fi
else
  step 6/6 "vLLM 스킵 (--with-vllm 옵션 미사용)"
  log "S 시나리오 시점에 별도 설치:"
  log "  pip install vllm"
  log "  또는: bash benchmark-setup.sh --with-vllm"
fi

# ─── 환경변수 sanity check ──────────────────────────────────
echo ""
log "aieev 환경변수"
echo "  AIRCLOUD_DEFAULT_API_BASE: ${AIRCLOUD_DEFAULT_API_BASE:-(unset)}"
echo "  AIRCLOUD_DEFAULT_MODEL:    ${AIRCLOUD_DEFAULT_MODEL:-(unset)}"

# ─── 완료 ────────────────────────────────────────────────────
echo ""
echo "=========================================="
log "✅ 셋업 완료"
echo "=========================================="
cat <<EOF

📁 작업 디렉토리: $BENCH_ROOT
🐍 venv 활성화:    source $VENV_DIR/bin/activate

다음 단계 — 시나리오 P (aieev API baseline):
  cd $JB_DIR
  source $VENV_DIR/bin/activate
  # 다음 turn에서 측정 스크립트 작성

⚠️ Dependency conflict 메시지는 무시 가능 (model-hosting-container-standards,
   huggingface-hub 등은 컨테이너 베이스 패키지 — 우리 측정 무관)

EOF
