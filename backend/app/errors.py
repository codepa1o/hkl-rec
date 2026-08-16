from __future__ import annotations


class RepositoryNotReadyError(RuntimeError):
    """在线操作没有配置运行时仓储时抛出。"""

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"PostgreSQL runtime repository is unavailable for `{operation}`. "
            "Configure NEWSREC_DATABASE_URL and wait for readiness."
        )
        self.operation = operation


class UnresolvedQueryError(ValueError):
    """搜索输入无法映射到已知 query_key 时抛出。"""

    def __init__(self, query_input: str) -> None:
        super().__init__("No matching query found. Try a suggested query.")
        self.query_input = query_input


class SearchIndexNotReadyError(RuntimeError):
    """启用混合搜索但缺少兼容制品时抛出。"""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Hybrid search index is unavailable: {detail}")
        self.detail = detail


class IdempotencyConflictError(ValueError):
    """同一事件 ID 被用于语义不同的载荷时抛出。"""


class ProfileNotInitializedError(LookupError):
    """Raised when an authenticated account has no profile projection row."""

    def __init__(self, user_id: int) -> None:
        super().__init__(f"Profile is not initialized for user_id={user_id}.")
        self.user_id = user_id


class ProfileSeedUnavailableError(RuntimeError):
    """Raised when reset cannot restore the user's configured cold-start seed."""

    def __init__(self, seed_key: str) -> None:
        super().__init__(f"Cold-start profile seed {seed_key!r} is unavailable.")
        self.seed_key = seed_key
