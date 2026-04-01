"""
Live pipeline verification test — runs inside the container.
Tests each component of the message handler pipeline with correct APIs.
"""
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/chat_app')


def test_spl_template_engine():
    from shared.spl_template_engine import SPLTemplateEngine
    engine = SPLTemplateEngine()
    tests = [
        'show me failed logins in the last hour',
        'count events by sourcetype',
        'find IP 10.0.0.1 in firewall logs',
        'top 10 users by login count',
    ]
    print('=== SPL Template Engine ===')
    for query in tests:
        result = engine.detect_intent(query)
        print(f'  [{result.query_type}] {query}')

    # generate_query returns (spl_query, QueryIntent, explanation)
    spl_tuple = engine.generate_query('show failed logins last hour')
    spl_query, intent, explanation = spl_tuple
    print(f'  Generated SPL: {spl_query}')
    print(f'  Explanation: {explanation}')
    assert spl_query and len(spl_query) > 5, f'SPL generation failed: {spl_query}'
    print('  PASSED\n')


def test_spl_analyzer():
    from shared.spl_robust_analyzer import RobustSPLAnalyzer
    analyzer = RobustSPLAnalyzer()
    test_queries = [
        'index=main | stats count by host',
        'index=_internal | sort - _time | head 10 | stats count by sourcetype',
        'index=main sourcetype=access_combined | where status>=400 | table _time host status',
    ]
    print('=== SPL Analyzer ===')
    for query in test_queries:
        result = analyzer.analyze(query)
        # AnalysisResult dataclass: is_valid, issues, recommendations, optimization_potential
        issues = len(result.issues)
        recs = len(result.recommendations)
        opt = result.optimization_potential
        print(f'  valid={result.is_valid}, issues={issues}, recs={recs}, opt_potential={opt} | {query[:60]}')
    print('  PASSED\n')


def test_confidence_scorer():
    from chat_app.confidence_scorer import score_confidence, format_confidence_for_user
    # score_confidence(local_spec_content, retrieved_chunks, user_query, ...)
    # chunks are List[dict]
    chunks = [
        {'collection': 'spl_docs', 'text': 'stats command counts events'},
        {'collection': 'spl_docs', 'text': 'use stats count by field'},
    ]
    spec_content = ['The stats command calculates aggregate statistics.']
    conf = score_confidence(spec_content, chunks, 'how to use stats command')
    # ScoredConfidence dataclass: score, label, reasoning
    print('=== Confidence Scorer ===')
    print(f'  score={conf.score:.2f}, label={conf.label}')
    print(f'  reasoning: {conf.reasoning[:80]}')
    user_msg = format_confidence_for_user(conf)
    print(f'  user_msg: {user_msg[:80]}')
    assert conf.score >= 0.0, 'Confidence score should be >= 0'
    assert conf.label in ('HIGH', 'MEDIUM', 'LOW', 'VERY_LOW'), f'Invalid label: {conf.label}'
    print('  PASSED\n')


def test_self_evaluator():
    from chat_app.self_evaluator import evaluate_response_quality
    # evaluate_response_quality(response, user_query, context, chunks_found)
    response_text = (
        'The stats command in Splunk calculates aggregate statistics over search results. '
        'Use stats count by host to count events per host.'
    )
    context = 'stats command counts events and calculates aggregate statistics. Use stats count by field_name to aggregate.'
    quality = evaluate_response_quality(
        response=response_text,
        user_query='how to use stats command',
        context=context,
        chunks_found=2,
    )
    # QualityScore dataclass: overall, completeness, grounding, hallucination_risk, spl_validity, recommended_action
    print('=== Self Evaluator ===')
    print(f'  overall={quality.overall:.2f}, completeness={quality.completeness:.2f}')
    print(f'  grounding={quality.grounding:.2f}, hallucination_risk={quality.hallucination_risk:.2f}')
    print(f'  recommended_action={quality.recommended_action}')
    assert quality.overall >= 0.0, 'Quality score should be >= 0'
    print('  PASSED\n')


def test_failure_analyzer():
    from chat_app.failure_analyzer import categorize_failure, categorize_quality_failure

    print('=== Failure Analyzer ===')
    # categorize_failure(exception, context) -> FailureReport dataclass
    try:
        raise ConnectionError("Ollama unreachable")
    except Exception as e:
        result = categorize_failure(e)
        print(f'  ConnectionError -> type={result.failure_type}, severity={result.severity}')
        assert result.failure_type is not None

    # categorize_quality_failure(chunks_found, confidence, response_length) -> Optional[FailureReport]
    qf = categorize_quality_failure(
        chunks_found=0,
        confidence=0.2,
        response_length=10,
    )
    if qf:
        print(f'  Low quality -> type={qf.failure_type}, severity={qf.severity}')
        print(f'  Recovery actions: {len(qf.recovery_actions)}')
    else:
        print(f'  Low quality -> no failure report (within tolerance)')
    print('  PASSED\n')


def test_knowledge_gap_detector():
    from chat_app.knowledge_gap_detector import detect_knowledge_gaps

    print('=== Knowledge Gap Detector ===')
    # detect_knowledge_gaps(user_query, retrieved_chunks: List[dict], chunk_threshold)
    chunks = [
        {'collection': 'general', 'text': 'some basic info about Splunk'},
    ]
    gaps = detect_knowledge_gaps('how to configure ITSI service analyzer', chunks)
    print(f'  Gaps found: {len(gaps)}')
    for g in gaps[:3]:
        # KnowledgeGap dataclass: topic, gap_type, severity, suggestion
        print(f'    - [{g.gap_type}] {g.topic}: {g.suggestion[:60]}')
    print('  PASSED\n')


def test_user_model():
    from chat_app.user_model import UserModel

    print('=== User Model ===')
    # UserModel is a dataclass with defaults
    model = UserModel()
    print(f'  Default expertise: {model.expertise_level}')
    print(f'  Default style: {model.preferred_style}')
    assert model.expertise_level == 'intermediate'

    # Create a beginner model
    beginner = UserModel(expertise_level='beginner', common_topics=['basic search'])
    print(f'  Beginner model: expertise={beginner.expertise_level}, topics={beginner.common_topics}')

    # Create an expert model
    expert = UserModel(expertise_level='expert', common_topics=['tstats', 'datamodels', 'distributed search'])
    print(f'  Expert model: expertise={expert.expertise_level}, topics={expert.common_topics}')
    print(f'  Expert satisfaction rate: {expert.satisfaction_rate:.2f}')
    print('  PASSED\n')


def test_intent_classifier():
    from chat_app.intent_classifier import IntentClassifier

    print('=== Intent Classifier ===')
    classifier = IntentClassifier()
    test_cases = [
        ('what is Splunk?', 2),
        ('index=main | stats count by host', 7),
        ('optimize index=main | sort _time | head 100 | stats count', 9),
        ('show me failed logins last hour', 6),
        ('how to configure props.conf', 5),
    ]
    for query, word_count in test_cases:
        result = classifier.classify(query, word_count)
        # QueryPlan has .intent attribute
        intent = result.intent if hasattr(result, 'intent') else str(result)
        print(f'  [{intent}] {query}')
    print('  PASSED\n')


def test_context_builder():
    from chat_app.context_builder import detect_config_context, detect_compound_query

    print('=== Context Builder ===')
    ctx = detect_config_context('how to configure props.conf for syslog')
    print(f'  Config context for "props.conf for syslog": {ctx}')

    ctx2 = detect_config_context('show me failed logins')
    print(f'  Config context for "show me failed logins": {ctx2}')

    compound = detect_compound_query('first search for errors then count by host and show top 10')
    print(f'  Compound query: {compound}')
    print('  PASSED\n')


def test_context_compressor():
    from chat_app.context_compressor import estimate_context_tokens, should_compress

    print('=== Context Compressor ===')
    # estimate_context_tokens(context: str) -> int
    # should_compress(context: str, max_tokens: int) -> bool
    context = 'What is Splunk? Splunk is a platform for searching and analyzing machine data. How do I search? Use the search bar.'
    tokens = estimate_context_tokens(context)
    needs_compress = should_compress(context)
    print(f'  Context length: {len(context)} chars')
    print(f'  Tokens estimated: {tokens}')
    print(f'  Needs compression (default 4000 threshold): {needs_compress}')
    assert tokens > 0, 'Token estimate should be > 0'
    assert not needs_compress, 'Short context should not need compression'

    # Test with large context
    large_context = 'x' * 20000  # ~5000 tokens
    assert should_compress(large_context), 'Large context should need compression'
    print(f'  Large context ({len(large_context)} chars) needs compression: True')
    print('  PASSED\n')


if __name__ == '__main__':
    tests = [
        test_spl_template_engine,
        test_spl_analyzer,
        test_confidence_scorer,
        test_self_evaluator,
        test_failure_analyzer,
        test_knowledge_gap_detector,
        test_user_model,
        test_intent_classifier,
        test_context_builder,
        test_context_compressor,
    ]

    passed = 0
    failed = 0
    errors = []
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            import traceback
            print(f'  FAILED: {e}')
            traceback.print_exc()
            print()
            failed += 1
            errors.append((test_fn.__name__, str(e)))

    print('===========================')
    print(f'Results: {passed} passed, {failed} failed out of {len(tests)} tests')
    if failed == 0:
        print('ALL PIPELINE COMPONENT TESTS PASSED')
    else:
        print(f'WARNING: {failed} test(s) failed:')
        for name, err in errors:
            print(f'  - {name}: {err}')
