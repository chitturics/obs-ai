"""
Full RAG pipeline end-to-end test with real data.
Tests: Intent → Retrieval → Context Building → LLM Generation → Quality Evaluation
Run inside the container: python3 /app/tests/test_rag_pipeline_live.py

NOTE: This test is designed to run INSIDE the container only.
It requires live ChromaDB, Ollama, and the full app environment.
When run via pytest outside the container, all tests are skipped.
"""
import asyncio
import sys
import os

import pytest

# Skip entire module when not running inside the container
_IN_CONTAINER = os.path.isdir('/app/chat_app') and os.path.isdir('/app/shared/public/documents')
pytestmark = pytest.mark.skipif(
    not _IN_CONTAINER,
    reason="RAG pipeline tests require container environment (/app/chat_app)"
)

if _IN_CONTAINER:
    sys.path.insert(0, '/app')
    sys.path.insert(0, '/app/chat_app')
    os.chdir('/app')


async def test_rag_pipeline(query, expected_intent=None):
    """Run a single query through the full RAG pipeline."""
    print(f"\n{'='*60}")
    print(f"QUERY: {query}")
    print(f"{'='*60}")

    # Stage 1: Intent Classification
    from chat_app.intent_classifier import IntentClassifier
    classifier = IntentClassifier()
    word_count = len(query.split())
    plan = classifier.classify(query, word_count)
    print(f"  [1] Intent: {plan.intent} (conf={plan.confidence:.2f}, skip_retrieval={plan.skip_retrieval})")
    if expected_intent:
        assert plan.intent == expected_intent, f"Expected {expected_intent}, got {plan.intent}"

    # Stage 2: Retrieval from ChromaDB
    from langchain_ollama import OllamaEmbeddings
    from langchain_chroma import Chroma
    from chromadb import PersistentClient
    from chromadb.config import Settings

    embeddings = OllamaEmbeddings(model="mxbai-embed-large", base_url="http://llm_api_service:11430")
    client = PersistentClient(path="/app/chroma_store", settings=Settings(anonymized_telemetry=False))
    store = Chroma(
        collection_name="assistant_memory_mxbai_embed_large",
        embedding_function=embeddings,
        client=client,
    )

    results = store.similarity_search_with_relevance_scores(query, k=5)
    print(f"  [2] Retrieved: {len(results)} chunks")
    for doc, score in results[:3]:
        source = doc.metadata.get("source", "?")
        preview = doc.page_content[:60].replace("\n", " ")
        print(f"      [{score:.3f}] {source}: {preview}")

    # Stage 3: Build context
    context_parts = []
    for doc, score in results:
        if score > 0.3:  # Relevance threshold
            context_parts.append(doc.page_content)
    context_text = "\n\n".join(context_parts[:5])
    print(f"  [3] Context: {len(context_text)} chars from {len(context_parts)} relevant chunks")

    # Stage 4: Confidence Scoring
    from chat_app.confidence_scorer import score_confidence
    chunks_as_dicts = [
        {"collection": doc.metadata.get("collection", "unknown"), "text": doc.page_content}
        for doc, score in results
    ]
    spec_content = [doc.page_content for doc, score in results if ".spec" in doc.metadata.get("source", "")]
    confidence = score_confidence(spec_content, chunks_as_dicts, query)
    print(f"  [4] Confidence: {confidence.score:.2f} ({confidence.label})")

    # Stage 5: LLM Generation with context
    from llm_utils import LLM
    from langchain_core.messages import HumanMessage, SystemMessage

    system_msg = (
        "You are a Splunk expert assistant. Answer based on the provided context. "
        "Be concise and accurate. If you include SPL, put it in code blocks.\n\n"
        f"Context:\n{context_text[:3000]}"
    )
    messages = [
        SystemMessage(content=system_msg),
        HumanMessage(content=query),
    ]
    response = await LLM.ainvoke(messages)
    answer = response.content.strip()
    print(f"  [5] LLM Response ({len(answer)} chars):")
    print(f"      {answer[:200]}")

    # Stage 6: Quality Evaluation
    from chat_app.self_evaluator import evaluate_response_quality
    quality = evaluate_response_quality(
        response=answer,
        user_query=query,
        context=context_text[:2000],
        chunks_found=len(results),
    )
    print(f"  [6] Quality: overall={quality.overall:.2f}, grounding={quality.grounding:.2f}, action={quality.recommended_action}")

    # Stage 7: Knowledge Gap Detection
    from chat_app.knowledge_gap_detector import detect_knowledge_gaps
    gaps = detect_knowledge_gaps(query, chunks_as_dicts)
    print(f"  [7] Knowledge gaps: {len(gaps)}")

    return {
        "query": query,
        "intent": plan.intent,
        "chunks_found": len(results),
        "confidence": confidence.score,
        "quality": quality.overall,
        "answer_length": len(answer),
        "gaps": len(gaps),
        "action": quality.recommended_action,
    }


async def main():
    print("=== Full RAG Pipeline End-to-End Test ===")
    print(f"Testing with 2061 documents in ChromaDB")

    test_cases = [
        ("how do I use the stats command in Splunk?", "spl_generation"),
        ("what is the difference between tstats and stats?", "spl_generation"),
        ("how to configure props.conf for syslog data?", "config_lookup"),
        ("show me failed logins in the last 24 hours", "spl_generation"),
        ("explain the tstats command and when to use it", "spl_generation"),
    ]

    results = []
    for query, expected_intent in test_cases:
        try:
            result = await test_rag_pipeline(query, expected_intent)
            results.append(result)
        except Exception as e:
            import traceback
            print(f"  ERROR: {e}")
            traceback.print_exc()
            results.append({"query": query, "error": str(e)})

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for r in results:
        if "error" in r:
            print(f"  FAIL: {r['query'][:50]} - {r['error']}")
        else:
            status = "PASS" if r["quality"] >= 0.5 and r["action"] == "send" else "WARN"
            print(f"  {status}: {r['query'][:50]} | quality={r['quality']:.2f} conf={r['confidence']:.2f} chunks={r['chunks_found']} gaps={r['gaps']}")

    passed = sum(1 for r in results if "error" not in r and r.get("quality", 0) >= 0.3)
    print(f"\n{passed}/{len(results)} tests produced quality responses")


if __name__ == "__main__":
    asyncio.run(main())
