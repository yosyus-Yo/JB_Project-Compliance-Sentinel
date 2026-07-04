"""qdrant_retriever.py — availability + HybridConfig (Qdrant 없이 graceful)."""
from __future__ import annotations

import pytest

from compliance_sentinel.qdrant_retriever import (
    HybridConfig,
    QdrantRetriever,
    availability_report,
    is_available,
)


class TestIsAvailable:
    def test_disabled_when_cs_disable_set(self, monkeypatch):
        monkeypatch.setenv("CS_DISABLE_QDRANT", "1")
        assert is_available() is False

    def test_returns_bool(self):
        assert isinstance(is_available(), bool)


class TestAvailabilityReport:
    def test_returns_dict(self):
        report = availability_report()
        assert isinstance(report, dict)

    def test_has_enabled_key(self):
        report = availability_report()
        # 'enabled' 또는 'available' 같은 상태 키 1개 이상
        assert any(k in report for k in ["enabled", "available", "status", "disabled"])


class TestHybridConfig:
    def test_construction_with_required_url(self):
        # 실제 시그니처: qdrant_url (required), collection, embedding_model, device, top_k, dense_weight, sparse_weight
        config = HybridConfig(qdrant_url="http://localhost:6333")
        assert config.qdrant_url == "http://localhost:6333"

    def test_default_collection_and_model(self, monkeypatch):
        monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
        monkeypatch.delenv("QDRANT_EMBEDDING_MODEL", raising=False)
        config = HybridConfig(qdrant_url="http://x")
        assert config.collection == "compliance_laws"
        assert "bge" in config.embedding_model.lower()

    def test_default_top_k_5(self):
        config = HybridConfig(qdrant_url="http://x")
        assert config.top_k == 5

    def test_default_weights_sum_to_1(self):
        config = HybridConfig(qdrant_url="http://x")
        assert config.dense_weight + config.sparse_weight == pytest.approx(1.0)

    def test_dense_weight_higher_than_sparse(self):
        """RRF 정책: dense가 keyword보다 가중치 ↑ (1024d semantic 우월)."""
        config = HybridConfig(qdrant_url="http://x")
        assert config.dense_weight > config.sparse_weight

    def test_override_via_constructor(self):
        config = HybridConfig(
            qdrant_url="http://x",
            collection="custom",
            top_k=10,
            dense_weight=0.6,
            sparse_weight=0.4,
        )
        assert config.collection == "custom"
        assert config.top_k == 10


class TestQdrantRetriever:
    def test_class_importable(self):
        assert QdrantRetriever is not None
