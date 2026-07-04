#!/usr/bin/env python3
"""LawKnowledgeBase의 법령/내부기준 article을 임베딩하여 Qdrant에 색인.

사용법:
  QDRANT_URL=http://localhost:6333 PYTHONPATH=src python3 scripts/qdrant_index.py

환경변수:
  QDRANT_URL              Qdrant 서버 주소 (기본 http://localhost:6333)
  QDRANT_COLLECTION       collection 이름 (기본 compliance_laws)
  QDRANT_EMBEDDING_MODEL  sentence-transformers 모델 (기본 BAAI/bge-m3)

Qdrant는 Docker 컨테이너로 로컬 구동한다 (외부 클라우드/비용 없음).
qdrant_retriever.py의 QdrantRetriever가 동일 collection/payload 스키마를 읽는다.
"""
from __future__ import annotations

import os
import sys

from compliance_sentinel.knowledge_base import LawKnowledgeBase

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "compliance_laws")
MODEL_NAME = os.environ.get("QDRANT_EMBEDDING_MODEL", "BAAI/bge-m3")


def main() -> int:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
    from sentence_transformers import SentenceTransformer

    kb = LawKnowledgeBase.from_json()
    articles = list(kb.articles)
    print(f"[1/4] KB 로드: {len(articles)}건")

    print(f"[2/4] 임베딩 모델 로드: {MODEL_NAME} (최초 1회 다운로드)")
    # device="cpu" 강제 — BGE-M3는 대형 모델이라 Apple MPS(GPU)에서 전체 배치를
    # 한 번에 올리면 메모리가 폭발한다(MPS OOM). CPU + 작은 batch_size로 안정 처리.
    embedder = SentenceTransformer(MODEL_NAME, device="cpu")

    # qdrant_retriever.QdrantRetriever.retrieve()가 payload의 law_name/article_no로
    # KB article을 역조회하므로, 색인 텍스트는 검색 품질용이고 payload는 식별자만 보관.
    texts = [f"{a.law_name} {a.title}\n{a.text}" for a in articles]
    vectors = embedder.encode(
        texts, batch_size=8, show_progress_bar=True, normalize_embeddings=True
    )
    dim = len(vectors[0])
    print(f"[3/4] 임베딩 완료: {len(vectors)}벡터 x {dim}차원")

    client = QdrantClient(url=QDRANT_URL)
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        COLLECTION,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    points = [
        PointStruct(
            id=i,
            vector=vectors[i].tolist(),
            payload={
                "law_name": a.law_name,
                "article_no": a.article_no,
                "title": a.title,
            },
        )
        for i, a in enumerate(articles)
    ]
    client.upsert(COLLECTION, points=points)
    count = client.count(COLLECTION).count
    print(f"[4/4] Qdrant 색인 완료: collection='{COLLECTION}' {count}건 @ {QDRANT_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
