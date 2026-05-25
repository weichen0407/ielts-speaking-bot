"""ReviewExtractor - parses LLM output into review points."""

import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import ReviewStore

from .store import ReviewPoint


@dataclass
class ExtractedPoint:
    """A review point extracted from LLM output."""
    content: str
    point_type: str
    topic: str
    source: str


class ReviewExtractor:
    """
    Parses LLM output into ReviewPoint objects.

    LLM Output Format:
    REVIEW: content, type={type}, topic={topic}
    """

    REVIEW_PATTERN = re.compile(
        r"^REVIEW:\s*(.+?),\s*type=(.+?),\s*topic=(.+?)$",
        re.IGNORECASE,
    )

    def parse_line(self, line: str) -> ExtractedPoint | None:
        """Parse a single line of LLM output."""
        line = line.strip()
        if not line:
            return None

        match = self.REVIEW_PATTERN.match(line)
        if match:
            content, point_type, topic = match.groups()
            return ExtractedPoint(
                content=content.strip(),
                point_type=point_type.strip(),
                topic=topic.strip(),
                source="llm",  # Will be set by caller
            )

        return None

    def parse(self, llm_output: str, default_source: str = "llm") -> list[ExtractedPoint]:
        """Parse full LLM output into review points."""
        results = []

        for line in llm_output.strip().split("\n"):
            extracted = self.parse_line(line)
            if extracted:
                extracted.source = default_source
                results.append(extracted)

        return results

    def extract_to_store(
        self,
        llm_output: str,
        store: "ReviewStore",
        source: str,
    ) -> list[ReviewPoint]:
        """
        Parse LLM output and add review points to store.

        Returns list of newly created points.
        """
        extracted_points = self.parse(llm_output, default_source=source)

        created = []
        for ext_point in extracted_points:
            point, was_created = store.get_or_create_point(
                content=ext_point.content,
                point_type=ext_point.point_type,
                topic=ext_point.topic,
                source=source,
            )
            if was_created:
                created.append(point)

        if created:
            store.save()

        return created
