"""Test direct ChromaDB retrieval in the container."""
import asyncio
import os
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/chat_app')


async def test_chromadb_retrieval():
    print("=== ChromaDB Direct Retrieval Test ===")
    import chromadb

    host = os.getenv("CHROMA_HOST", "chat_chroma_db")
    port = int(os.getenv("CHROMA_PORT", "8000"))
    print(f"  Connecting to ChromaDB at {host}:{port}")

    client = chromadb.HttpClient(host=host, port=port)
    heartbeat = client.heartbeat()
    print(f"  Heartbeat: {heartbeat}")

    collections = client.list_collections()
    print(f"  Collections: {len(collections)}")
    for col in collections:
        count = col.count()
        print(f"    - {col.name}: {count} documents")

    # Query each collection
    queries = [
        "What is Splunk?",
        "how to use stats command",
        "configure props.conf for syslog",
    ]

    print()
    for col in collections:
        if col.count() == 0:
            continue
        for q in queries:
            results = col.query(query_texts=[q], n_results=3)
            docs = results.get("documents", [[]])[0]
            distances = results.get("distances", [[]])[0]
            if docs:
                best_dist = distances[0] if distances else -1
                preview = docs[0][:100].replace("\n", " ")
                print(f"  [{col.name}] '{q}' -> best_dist={best_dist:.3f} | {preview}")

    print()
    print("  PASSED")


async def test_llm_generation():
    print("\n=== LLM Generation Test ===")
    try:
        from llm_utils import LLM
        if LLM is None:
            print("  LLM not initialized, attempting init...")
            from llm_utils import init_llm
            init_llm()
            from llm_utils import LLM as llm
        else:
            llm = LLM

        print(f"  LLM type: {type(llm).__name__}")
        print(f"  LLM base_url: {getattr(llm, 'base_url', 'N/A')}")

        # Simple test - invoke with a basic question
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content="What is Splunk? Answer in one sentence.")])
        answer = response.content.strip()
        print(f"  Response: {answer[:200]}")
        assert len(answer) > 10, "LLM response too short"
        print("  PASSED")
    except Exception as e:
        import traceback
        print(f"  ERROR: {e}")
        traceback.print_exc()


async def test_full_rag_pipeline():
    print("\n=== Full RAG Pipeline (Retrieval + LLM) ===")
    import chromadb

    host = os.getenv("CHROMA_HOST", "chat_chroma_db")
    port = int(os.getenv("CHROMA_PORT", "8000"))

    client = chromadb.HttpClient(host=host, port=port)
    collections = client.list_collections()

    # Step 1: Retrieve context
    query = "What is Splunk?"
    all_context = []
    for col in collections:
        if col.count() == 0:
            continue
        results = col.query(query_texts=[query], n_results=3)
        docs = results.get("documents", [[]])[0]
        all_context.extend(docs)

    context_text = "\n".join(all_context[:5]) if all_context else "No context available."
    print(f"  Retrieved {len(all_context)} chunks, using top 5")

    # Step 2: Generate with LLM
    try:
        from llm_utils import LLM
        if LLM is None:
            from llm_utils import init_llm
            init_llm()
            from llm_utils import LLM as llm
        else:
            llm = LLM

        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content=f"Answer based on this context:\n{context_text[:2000]}"),
            HumanMessage(content=query),
        ]
        response = await llm.ainvoke(messages)
        answer = response.content.strip()
        print(f"  RAG Answer: {answer[:300]}")
        assert len(answer) > 20, "RAG response too short"
        print("  PASSED")
    except Exception as e:
        import traceback
        print(f"  ERROR: {e}")
        traceback.print_exc()


async def main():
    await test_chromadb_retrieval()
    await test_llm_generation()
    await test_full_rag_pipeline()
    print("\n=== ALL END-TO-END TESTS COMPLETE ===")


if __name__ == "__main__":
    asyncio.run(main())
