# SPDX-License-Identifier: AGPL-3.0-or-later

from typing import Any
from ..backend.slob import Blob

class DictEntry(object):
    def __init__(self, dict_id: str, dict_name: str, term_id: int, term: str):
        self._dict_id: str = dict_id
        self._dict_name: str = dict_name
        self._term_id: int = term_id
        self._term: str = term

    @property
    def dict_id(self) -> str:
        return self._dict_id

    @property
    def dict_name(self) -> str:
        return self._dict_name

    @property
    def term_id(self) -> int:
        return self._term_id

    @property
    def term(self) -> str:
        return self._term

    def __str__(self) -> str:
        return self.term


class DictEntryContent(DictEntry):
    def __init__(self,
        dict_id: str,
        dict_name: str,
        term_id: int,
        term: str,
        content_type: str,
        content: Any
    ):
        super().__init__(dict_id, dict_name, term_id, term)
        self._content = content
        self._content_type = content_type

    @property
    def content(self) -> Any:
        return self._content

    @property
    def content_type(self) -> str:
        return self._content_type
