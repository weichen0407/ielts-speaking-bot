import json
from pathlib import Path

from subagent._shared.registry import discover_processors
from subagent.cross_session.benative_article.processor import BenativeArticleProcessor
from subagent.single_session.benative_review.processor import BenativeReviewProcessor


def test_benative_article_processor_parses_and_writes_side_artifacts(tmp_path: Path) -> None:
    processor = BenativeArticleProcessor()
    raw = "\n".join([
        "ARTICLE\tarticle_001\tFamily Meals\tfamily\tB1\tA short article about family meals.",
        "PAIR\tarticle_001\t0\t0\tFamilies often build stronger relationships by spending time together.\t家人经常通过共度时光来建立更牢固的关系。",
        "ENTITY\tarticle_001\tfamily meals\tterm\tfamily meals\t家庭聚餐\tfamily dinner,shared meal\t0",
    ])

    parsed = processor.parse_llm_output(raw)
    output_path = tmp_path / "persona" / "processor" / "benative" / "article.jsonl"
    processor.serialize(parsed, output_path, "both")

    assert output_path.exists()
    assert (tmp_path / "persona" / "processor" / "benative" / "article.md").exists()

    article = json.loads((tmp_path / "persona" / "benative" / "articles" / "article_001.json").read_text())
    pair = json.loads((tmp_path / "persona" / "benative" / "pairs" / "article_001.jsonl").read_text().splitlines()[0])
    entity = json.loads((tmp_path / "persona" / "benative" / "entities" / "article_001.jsonl").read_text().splitlines()[0])

    assert article["title"] == "Family Meals"
    assert pair["sentence_index"] == 0
    assert pair["zh"].startswith("家人")
    assert entity["surface"] == "family meals"
    assert entity["aliases"] == ["family dinner", "shared meal"]
    assert entity["source_sentence_indexes"] == [0]


def test_benative_article_processor_reads_markdown_source(tmp_path: Path) -> None:
    source = tmp_path / "persona" / "benative" / "sources" / "article_001.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\n"
        "id: article_001\n"
        "title: Family Meals\n"
        "topic: family\n"
        "level: B1\n"
        "---\n"
        "Families often build stronger relationships by spending time together.\n",
        encoding="utf-8",
    )

    rows = BenativeArticleProcessor().read(source)

    assert rows == [{
        "article_id": "article_001",
        "title": "Family Meals",
        "topic": "family",
        "level": "B1",
        "source_type": "fixed",
        "source_url": None,
        "content": "Families often build stronger relationships by spending time together.",
    }]


def test_benative_review_processor_parses_review_rows() -> None:
    processor = BenativeReviewProcessor()
    raw = (
        "article_001\t0\t82\t78\tgrammar\t"
        "Family can build strong relationship when they spend time together.\t"
        "Families often build stronger relationships by spending time together.\t"
        "Families can build stronger relationships when they spend time together.\t"
        "relationship 应该用复数，stronger relationships 更自然。"
    )

    parsed = processor.parse_llm_output(raw)

    assert len(parsed) == 1
    assert parsed[0].article_id == "article_001"
    assert parsed[0].sentence_index == 0
    assert parsed[0].accuracy_score == 82
    assert parsed[0].issue_type == "grammar"


def test_benative_processors_are_discoverable() -> None:
    processors = discover_processors()

    assert processors["benative_article"] is BenativeArticleProcessor
    assert processors["benative_review"] is BenativeReviewProcessor
