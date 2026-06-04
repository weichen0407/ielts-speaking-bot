from pathlib import Path

from nanobot.benative.events import append_benative_response, benative_responses_path
from subagent._shared.benative_schema import BenativeResponse


def test_append_benative_response_writes_global_event_log(tmp_path: Path) -> None:
    response = BenativeResponse(
        session_uuid="session-1",
        article_id="article_001",
        sentence_index=0,
        zh="家人经常通过共度时光来建立更牢固的关系。",
        standard_en="Families often build stronger relationships by spending time together.",
        user_en="Family can build strong relationship when they spend time together.",
        timestamp="2026-06-04T12:00:00Z",
    )

    path = append_benative_response(tmp_path, response)

    assert path == benative_responses_path(tmp_path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert '"session_uuid":"session-1"' in text
    assert '"article_id":"article_001"' in text
