"""A proved byte-version mismatch, distinct from unavailable or unbound input."""


class SourceVersionMismatch(ValueError):
    """Only an actual byte read can supply the observed digest."""

    def __init__(self, literal: str, expected: str, observed: str, message: str) -> None:
        super().__init__(message)
        self.literal = literal
        self.expected_sha256 = expected
        self.observed_sha256 = observed
