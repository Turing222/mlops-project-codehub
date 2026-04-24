from pathlib import Path

import pytest

from evals.common import load_samples


def test_load_samples_supports_v1_fields(tmp_path: Path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        (
            '{"id":"case-1","query":"hello","kb_id":null,'
            '"category":"fact","retrieval_mode":"hybrid",'
            '"expected_chunk_ids":["c1"],"expected_keywords":["kw"],'
            '"reference_answer":"ref","must_refuse":true,'
            '"notes":"note"}\n'
        ),
        encoding="utf-8",
    )

    samples = load_samples(dataset)

    assert len(samples) == 1
    sample = samples[0]
    assert sample.id == "case-1"
    assert sample.category == "fact"
    assert sample.retrieval_mode == "hybrid"
    assert sample.expected_chunk_ids == ["c1"]
    assert sample.expected_keywords == ["kw"]
    assert sample.reference_answer == "ref"
    assert sample.must_refuse is True
    assert sample.notes == "note"


def test_load_samples_rejects_invalid_retrieval_mode(tmp_path: Path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        '{"query":"hello","retrieval_mode":"bm25"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="retrieval_mode"):
        load_samples(dataset)
