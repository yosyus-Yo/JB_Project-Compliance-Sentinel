"""Qdrant + BGE-M3 임베딩 기반 hybrid retriever (offline-first).

설계:
  - qdrant-client + sentence-transformers SDK 부재 시 silent fallback → 기존 retriever.py 사용
  - is_available() == True이면 dense + sparse hybrid 검색 활성
  - retrieve() 인터페이스는 기존 retriever.retrieve_context()와 동일 시그니처
  - production 시점: pip install qdrant-client sentence-transformers + QDRANT_URL 환경변수

본 turn은 wrapper interface + 단위 테스트 통과 (fallback path)까지 구현.
실제 Qdrant cluster 통합은 사용자 환경 + cost 결정 후 별도 phase.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .knowledge_base import LawKnowledgeBase
from .models import LawArticle
from .retriever import retrieve_context as keyword_retrieve_context
from .agent_shield_bridge import resilient_tool_call

# qdrant-client optional
try:  # pragma: no cover
    from qdrant_client import QdrantClient  # type: ignore
    _HAS_QDRANT = True
except Exception:  # pragma: no cover
    _HAS_QDRANT = False

# sentence-transformers optional (BGE-M3)
try:  # pragma: no cover
    from sentence_transformers import SentenceTransformer  # type: ignore
    _HAS_ST = True
except Exception:  # pragma: no cover
    _HAS_ST = False


def availability_report() -> dict:
    """Return Qdrant/BGE-M3 readiness diagnostics without raising."""

    deterministic = os.environ.get("CS_DETERMINISTIC_MODE") == "1"
    return {
        "enabled": (not deterministic) and _HAS_QDRANT and _HAS_ST and bool(os.environ.get("QDRANT_URL")),
        "has_qdrant_client": _HAS_QDRANT,
        "has_sentence_transformers": _HAS_ST,
        "qdrant_url_configured": bool(os.environ.get("QDRANT_URL")),
        "deterministic_mode": deterministic,
        "collection": os.environ.get("QDRANT_COLLECTION", "compliance_laws"),
        "embedding_model": os.environ.get("QDRANT_EMBEDDING_MODEL", "BAAI/bge-m3"),
        "fallback": "keyword_fallback" if deterministic or not (_HAS_QDRANT and _HAS_ST and bool(os.environ.get("QDRANT_URL"))) else "hybrid_keyword_qdrant_rrf",
    }


def is_available() -> bool:
    """Qdrant hybrid 검색 활성 조건.

    - qdrant-client + sentence-transformers SDK 둘 다 설치
    - QDRANT_URL 환경변수 존재
    - CS_DETERMINISTIC_MODE=1 시 강제 비활성 (fallback로)
    """
    return bool(availability_report()["enabled"])


@dataclass
class HybridConfig:
    qdrant_url: str
    collection: str = os.environ.get("QDRANT_COLLECTION", "compliance_laws")
    embedding_model: str = os.environ.get("QDRANT_EMBEDDING_MODEL", "BAAI/bge-m3")
    # device 기본 "cpu" — BGE-M3는 대형 모델이라 Apple MPS(GPU)에서 OOM이 난다.
    # GPU 환경에서 가속하려면 QDRANT_EMBEDDING_DEVICE=cuda 등으로 override.
    device: str = os.environ.get("QDRANT_EMBEDDING_DEVICE", "cpu")
    top_k: int = 5
    dense_weight: float = 0.7
    sparse_weight: float = 0.3


class QdrantRetriever:
    """Hybrid (dense+sparse) 검색 wrapper.

    설정이 안 됐을 때는 retrieve()가 keyword fallback을 그대로 반환.
    """

    def __init__(self, *, kb: Optional[LawKnowledgeBase] = None, config: Optional[HybridConfig] = None) -> None:
        self.kb = kb or LawKnowledgeBase.from_json()
        self.config = config
        self._client: Optional[object] = None
        self._embedder: Optional[object] = None
        if is_available():  # pragma: no cover
            cfg = config or HybridConfig(qdrant_url=os.environ["QDRANT_URL"])
            self.config = cfg
            try:
                self._client = QdrantClient(url=cfg.qdrant_url)
                self._embedder = SentenceTransformer(cfg.embedding_model, device=cfg.device)
            except Exception:
                self._client = None
                self._embedder = None

    @property
    def enabled(self) -> bool:
        return self._client is not None and self._embedder is not None

    def retrieve(self, text: str, *, limit: int = 5) -> list[LawArticle]:
        """검색 인터페이스. 활성 시 hybrid, 부재 시 keyword fallback."""
        if not self.enabled:
            return keyword_retrieve_context(text, self.kb, limit=limit)

        # pragma: no cover — 실제 Qdrant 호출 경로
        try:
            query_vec = self._embedder.encode(text).tolist()  # type: ignore
            assert self._client is not None
            # 오류회복(가이드 제2장): read는 멱등 → retry+timeout+circuit. 최종 실패는
            # 아래 except가 keyword fallback으로 graceful degradation.
            results = resilient_tool_call(
                lambda: self._client.search(
                    collection_name=(self.config or HybridConfig(qdrant_url="")).collection,
                    query_vector=query_vec,
                    limit=limit,
                ),
                tool_name="qdrant_search",
                idempotent=True,
                timeout_s=5.0,
                max_attempts=2,
            )
            # KB에서 매칭되는 article로 변환
            articles: list[LawArticle] = []
            for r in results:
                law_name = r.payload.get("law_name", "")
                article_no = r.payload.get("article_no", "")
                article = self.kb.get_article(law_name, article_no)
                if article:
                    articles.append(article)
            return articles or keyword_retrieve_context(text, self.kb, limit=limit)
        except Exception:
            return keyword_retrieve_context(text, self.kb, limit=limit)
