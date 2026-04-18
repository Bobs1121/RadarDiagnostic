# -*- coding: utf-8 -*-
"""
Time synchronization between bag (ROS nanoseconds) and blf (Unix epoch seconds).
"""
from typing import Optional


class TimeSync:
    """
    Aligns timestamps between bag (nanosecond ROS time) and blf (Unix epoch seconds).

    Strategy: compute offset between bag start and blf start, then convert either
    direction using that offset. Supports manual offset override.
    """

    def __init__(
        self,
        bag_start_ns: Optional[int] = None,
        bag_end_ns: Optional[int] = None,
        blf_start_sec: Optional[float] = None,
        blf_end_sec: Optional[float] = None,
        manual_offset_sec: Optional[float] = None,
    ):
        self.bag_start_ns = bag_start_ns
        self.bag_end_ns = bag_end_ns
        self.blf_start_sec = blf_start_sec
        self.blf_end_sec = blf_end_sec

        if manual_offset_sec is not None:
            self._offset_sec = manual_offset_sec
        elif bag_start_ns is not None and blf_start_sec is not None:
            bag_start_sec = bag_start_ns / 1e9
            self._offset_sec = blf_start_sec - bag_start_sec
        else:
            self._offset_sec = 0.0

    @property
    def offset_sec(self) -> float:
        """Offset to add to bag_sec to get blf_sec."""
        return self._offset_sec

    def bag_ns_to_blf_sec(self, bag_ns: int) -> float:
        """Convert bag timestamp (ns) to blf timestamp (Unix epoch sec)."""
        return (bag_ns / 1e9) + self._offset_sec

    def blf_sec_to_bag_ns(self, blf_sec: float) -> int:
        """Convert blf timestamp (Unix epoch sec) to bag timestamp (ns)."""
        return round((blf_sec - self._offset_sec) * 1e9)

    def bag_ns_to_relative_sec(self, bag_ns: int) -> float:
        """Convert bag timestamp to relative seconds from bag start."""
        if self.bag_start_ns is not None:
            return (bag_ns - self.bag_start_ns) / 1e9
        return bag_ns / 1e9

    def blf_sec_to_relative_sec(self, blf_sec: float) -> float:
        """Convert blf timestamp to relative seconds from blf start."""
        if self.blf_start_sec is not None:
            return blf_sec - self.blf_start_sec
        return blf_sec

    def get_overlap_range(self) -> Optional[tuple[float, float]]:
        """
        Find the overlapping time range between bag and blf (in relative seconds).
        Returns (start_relative_sec, end_relative_sec) or None if no overlap.
        """
        if not all([self.bag_start_ns, self.bag_end_ns, self.blf_start_sec, self.blf_end_sec]):
            return None
        bag_start_blf = self.bag_ns_to_blf_sec(self.bag_start_ns)
        bag_end_blf = self.bag_ns_to_blf_sec(self.bag_end_ns)
        overlap_start = max(bag_start_blf, self.blf_start_sec)
        overlap_end = min(bag_end_blf, self.blf_end_sec)
        if overlap_start >= overlap_end:
            return None
        return (
            overlap_start - min(bag_start_blf, self.blf_start_sec),
            overlap_end - min(bag_start_blf, self.blf_start_sec),
        )

    def summary(self) -> dict:
        return {
            "offset_sec": self._offset_sec,
            "bag_duration_sec": (self.bag_end_ns - self.bag_start_ns) / 1e9 if self.bag_start_ns and self.bag_end_ns else None,
            "blf_duration_sec": (self.blf_end_sec - self.blf_start_sec) if self.blf_start_sec and self.blf_end_sec else None,
            "overlap": self.get_overlap_range(),
        }
