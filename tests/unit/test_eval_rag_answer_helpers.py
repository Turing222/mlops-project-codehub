from evals.eval_rag_answer import _char_f1, _compute_answer_score, _score_refusal


def test_char_f1_accounts_for_repeated_characters():
    assert _char_f1("aaaa", "aa") == 2 / 3


def test_score_refusal_detects_common_refusal_language():
    assert _score_refusal("抱歉，当前提供的内容里未找到相关信息。") == 1.0
    assert _score_refusal("这是一个确定答案。") == 0.0


def test_compute_answer_score_prefers_refusal_metric_for_abstention():
    assert (
        _compute_answer_score(
            must_refuse=True,
            keyword_recall=0.8,
            reference_f1=0.7,
            refusal_score=1.0,
        )
        == 1.0
    )
    assert (
        _compute_answer_score(
            must_refuse=False,
            keyword_recall=0.8,
            reference_f1=0.6,
            refusal_score=None,
        )
        == 0.7
    )
