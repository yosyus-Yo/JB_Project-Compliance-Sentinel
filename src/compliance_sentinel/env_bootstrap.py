"""Minimal .env loader (stdlib only, no python-dotenv dependency).

프로젝트 루트의 .env를 읽어 os.environ에 주입한다. 이미 설정된 환경변수는
덮어쓰지 않는다 (명시적 export 우선). 엔트리포인트 최상단에서 1회 호출한다.

python-dotenv 의존성을 추가하지 않기 위해 stdlib만 사용한다.
"""
from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env_file(path: Path | str | None = None, *, override: bool = False) -> int:
    """Load ``KEY=VALUE`` lines from a .env file into ``os.environ``.

    반환값: 실제로 주입한 key 수. 파일 부재 시 0 (에러 없음).

    규칙:
      - 빈 줄 / ``#`` 주석 줄은 무시
      - ``export KEY=VAL`` 접두어 제거
      - 값 양끝의 홑/겹따옴표 1쌍 제거
      - ``override=False`` (기본): 이미 os.environ에 있으면 건너뜀
    """
    env_path = Path(path) if path is not None else _PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return 0
    applied = 0
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        applied += 1
    return applied
