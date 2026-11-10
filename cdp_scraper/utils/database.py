"""Kontrak sumber data (implementasi disediakan aplikasi, mis. MySQL/Postgres)."""
from typing import List, Optional, Protocol


class KeywordSource(Protocol):
    def get_all_keywords_by_group(self, id_topic) -> List[str]:
        ...


class AccountSource(Protocol):
    def get_active_account(self) -> Optional[dict]:
        ...
