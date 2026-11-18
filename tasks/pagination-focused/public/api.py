from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class Page:
    items: Iterable
    next_cursor: object = None
