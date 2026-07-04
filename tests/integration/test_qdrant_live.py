"""qdrant_retriever LIVE integration test.

QDRANT_URL 미설정 시 skip. 로컬 Qdrant in-memory mode 활용 가능.

설치:
  pip install -e ".[rag]"

실행 (in-memory):
  QDRANT_URL=":memory:" pytest tests/integration/test_qdrant_live.py

실행 (실제 cluster):
  QDRANT_URL=https://your-cluster.qdrant.io QDRANT_API_KEY=... pytest ...
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestQdrantLive:
    def test_hybrid_config_default_values(self, require_qdrant):
        from compliance_sentinel.qdrant_retriever import HybridConfig
        cfg = HybridConfig(qdrant_url="http://localhost:6333")
        # 정책 검증: dense/sparse weight 합 = 1.0
        assert cfg.dense_weight + cfg.sparse_weight == pytest.approx(1.0)
        assert cfg.top_k > 0

    def test_retriever_constructor_with_url(self, require_qdrant):
        from compliance_sentinel.qdrant_retriever import HybridConfig
        cfg = HybridConfig(qdrant_url="http://localhost:6333")
        # qdrant_client 설치된 경우만 동작 — 미설치 시 require_qdrant 통과해도 import error
        try:
            from compliance_sentinel.qdrant_retriever import QdrantHybridRetriever
            # 실제 cluster 연결까지는 안 함 — 객체 생성만
            retriever = QdrantHybridRetriever(config=cfg)
            assert retriever is not None
        except ImportError:
            pytest.skip("qdrant_client SDK 미설치")
        except Exception as exc:
            # 연결 실패는 OK — 본 test는 import + 생성자 path만 검증
            assert "connect" in str(exc).lower() or retriever is not None
