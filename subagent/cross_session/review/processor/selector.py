"""ReviewSelector - selects review points for quiz."""

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import ReviewStore, ReviewPoint, PointIndex


class ReviewSelector:
    """
    Selects review points for quiz based on familiarity.

    Selection strategy:
    - Sort by familiarity ascending (lowest first)
    - Select top N points
    """

    def __init__(self, threshold: int = 3):
        self.threshold = threshold

    def select(
        self,
        store: "ReviewStore",
        count: int = 5,
        exclude_ids: list[str] | None = None,
    ) -> list[tuple["ReviewPoint", "PointIndex"]]:
        """
        Select review points for quiz.

        Args:
            store: ReviewStore instance
            count: Number of points to select
            exclude_ids: Point IDs to exclude (e.g., already asked today)

        Returns:
            List of (ReviewPoint, PointIndex) tuples sorted by familiarity ascending
        """
        exclude_ids = set(exclude_ids or [])

        # Query points, excluding those in the exclude list
        all_points = store.query_points()

        filtered = [
            (point, idx) for point, idx in all_points
            if point.id not in exclude_ids
        ]

        # Sort by familiarity ascending (lowest first)
        filtered.sort(key=lambda x: x[1].familiarity)

        # Select top N
        selected = filtered[:count]

        return selected

    def select_with_fallback(
        self,
        store: "ReviewStore",
        count: int = 5,
        exclude_ids: list[str] | None = None,
    ) -> list[tuple["ReviewPoint", "PointIndex"]]:
        """
        Select review points with fallback to retired if not enough active.

        If active points (familiarity < threshold) < count,
        fill remaining slots with retired points.
        """
        exclude_ids = set(exclude_ids or [])

        # First, select from points with familiarity < threshold
        active_points = store.query_points(max_familiarity=self.threshold - 1)

        active_filtered = [
            (point, idx) for point, idx in active_points
            if point.id not in exclude_ids
        ]
        active_filtered.sort(key=lambda x: x[1].familiarity)

        selected = active_filtered[:count]

        # If not enough, fill with higher familiarity points
        if len(selected) < count:
            remaining_needed = count - len(selected)
            selected_ids = {p.id for p, _ in selected}

            # Get higher familiarity points
            high_points = store.query_points(min_familiarity=self.threshold)
            high_filtered = [
                (point, idx) for point, idx in high_points
                if point.id not in exclude_ids and point.id not in selected_ids
            ]
            high_filtered.sort(key=lambda x: x[1].familiarity)

            selected.extend(high_filtered[:remaining_needed])

        return selected
