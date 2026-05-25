"""ReviewStore - manages review points and index."""

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ReviewPoint:
    """A single review point."""
    id: str
    content: str
    type: str
    topic: str
    source: str
    created_at: str | None = None

    @staticmethod
    def create(content: str, point_type: str, topic: str, source: str) -> "ReviewPoint":
        """Create a new review point with auto-generated ID."""
        return ReviewPoint(
            id=f"rp{uuid.uuid4().hex[:8]}",
            content=content,
            type=point_type,
            topic=topic,
            source=source,
            created_at=None,
        )


@dataclass
class PointIndex:
    """Index entry for a review point."""
    familiarity: int = 0
    attempts: int = 0
    question_type: str = "sentence_use"


class ReviewStore:
    """
    Manages review_points.jsonl and review_index.json.

    review_points.jsonl - stores the actual review points
    review_index.json - stores familiarity, attempts, question_type per point
    """

    DEFAULT_THRESHOLD = 3

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.points_path = self.data_dir / "review_points.jsonl"
        self.index_path = self.data_dir / "review_index.json"
        self.points: dict[str, ReviewPoint] = {}
        self.index: dict[str, PointIndex] = {}
        self._threshold = self.DEFAULT_THRESHOLD
        self._load()

    def _load(self) -> None:
        """Load points and index from files."""
        # Load points
        if self.points_path.exists():
            with open(self.points_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        self.points[data["id"]] = ReviewPoint(**data)

        # Load index
        if self.index_path.exists():
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.index = {
                    pid: PointIndex(**idx) for pid, idx in data.get("points", {}).items()
                }

    def save(self) -> None:
        """Save points to JSONL and index to JSON."""
        # Save points (append new ones only)
        existing_ids = set()
        if self.points_path.exists():
            with open(self.points_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        existing_ids.add(data["id"])

        with open(self.points_path, "a", encoding="utf-8") as f:
            for point in self.points.values():
                if point.id not in existing_ids:
                    f.write(json.dumps(asdict(point), ensure_ascii=False) + "\n")

        # Save index
        index_data = {
            "points": {pid: asdict(idx) for pid, idx in self.index.items()}
        }
        tmp_path = self.index_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        tmp_path.replace(self.index_path)

    def add_point(self, point: ReviewPoint) -> None:
        """Add a new review point."""
        self.points[point.id] = point
        if point.id not in self.index:
            self.index[point.id] = PointIndex()

    def get_point(self, point_id: str) -> ReviewPoint | None:
        """Get a review point by ID."""
        return self.points.get(point_id)

    def get_index(self, point_id: str) -> PointIndex | None:
        """Get index for a point by ID."""
        return self.index.get(point_id)

    def update_familiarity(self, point_id: str, correct: bool) -> None:
        """
        Update familiarity score.

        Args:
            point_id: ID of the point
            correct: True if answered correctly, False otherwise
        """
        if point_id not in self.index:
            self.index[point_id] = PointIndex()

        idx = self.index[point_id]
        idx.attempts += 1
        if correct:
            idx.familiarity += 1

    def query_points(
        self,
        min_familiarity: int | None = None,
        max_familiarity: int | None = None,
        limit: int | None = None,
    ) -> list[tuple[ReviewPoint, PointIndex]]:
        """
        Query points by familiarity range.

        Returns list of (point, index) tuples sorted by familiarity ascending.
        """
        results = []

        for point_id, point in self.points.items():
            idx = self.index.get(point_id, PointIndex())

            if min_familiarity is not None and idx.familiarity < min_familiarity:
                continue
            if max_familiarity is not None and idx.familiarity > max_familiarity:
                continue

            results.append((point, idx))

        # Sort by familiarity ascending (lowest first)
        results.sort(key=lambda x: x[1].familiarity)

        if limit:
            results = results[:limit]

        return results

    def set_threshold(self, threshold: int) -> None:
        """Set the familiarity threshold."""
        self._threshold = threshold

    def get_threshold(self) -> int:
        """Get the familiarity threshold."""
        return self._threshold

    def find_by_content(self, content: str) -> ReviewPoint | None:
        """Find a point by exact content match."""
        for point in self.points.values():
            if point.content == content:
                return point
        return None

    def get_or_create_point(
        self,
        content: str,
        point_type: str,
        topic: str,
        source: str,
    ) -> tuple[ReviewPoint, bool]:
        """
        Get existing point by content or create new one.

        Returns (point, created) where created is True if new point was created.
        """
        existing = self.find_by_content(content)
        if existing:
            return existing, False

        point = ReviewPoint.create(content, point_type, topic, source)
        self.add_point(point)
        return point, True
