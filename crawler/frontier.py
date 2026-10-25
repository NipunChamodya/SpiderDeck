"""Bounded deterministic topic priority queue; authorization stays in Collector."""
import heapq


class TopicFrontier:
    def __init__(self, maximum: int):
        if maximum <= 0:
            raise ValueError('Frontier must have a positive bound.')
        self.maximum = maximum
        self._heap: list[tuple[float, int, str]] = []
        self._urls: set[str] = set()

    def append(self, item: tuple[str, int], priority: float = 0) -> bool:
        url, depth = item
        if url in self._urls or len(self._heap) >= self.maximum:
            return False
        heapq.heappush(self._heap, (-priority, depth, url))
        self._urls.add(url)
        return True

    def popleft(self) -> tuple[str, int]:
        _, depth, url = heapq.heappop(self._heap)
        self._urls.remove(url)
        return url, depth

    def __len__(self) -> int:
        return len(self._heap)
