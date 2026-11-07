"""The result type shared by the fetch pipeline and its resolvers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    final_url: str
    title: str
    description: str
    source: str
    creator: str
    date: str
    isbn: str
    canonical: str
    title_noisy: bool
    error: str

    @classmethod
    def disabled(cls, url: str, title: str = "") -> "FetchResult":
        return cls(
            ok=False,
            final_url=url,
            title=title,
            description="",
            source="",
            creator="",
            date="",
            isbn="",
            canonical="",
            title_noisy=False,
            error="fetch disabled",
        )

    @classmethod
    def failed(cls, url: str, error: str) -> "FetchResult":
        return cls(
            ok=False,
            final_url=url,
            title="",
            description="",
            source="",
            creator="",
            date="",
            isbn="",
            canonical="",
            title_noisy=False,
            error=error,
        )
