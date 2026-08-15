from types import SimpleNamespace

from backend.app import dependencies


class CachedFactory:
    def __init__(self, value: object, size: int) -> None:
        self.value = value
        self.size = size

    def cache_info(self) -> SimpleNamespace:
        return SimpleNamespace(currsize=self.size)

    def __call__(self) -> object:
        return self.value


class CloseProbe:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_auth_repository_closes_even_if_runtime_repository_was_never_created(monkeypatch) -> None:
    auth = CloseProbe()
    monkeypatch.setattr(dependencies, "get_runtime_repository", CachedFactory(None, 0))
    monkeypatch.setattr(dependencies, "get_auth_repository", CachedFactory(auth, 1))

    dependencies.close_runtime_repository()

    assert auth.closed
