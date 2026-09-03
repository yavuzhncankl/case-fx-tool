"""The single error shape this service is allowed to return.

Every failure path — validation, upstream, or a bug we did not foresee — ends
up as `{"error": "<machine_code>", "message": "<a sentence a person reads>"}`
with a non-2xx status. The caller is a language model that will read the
message out to a customer, so the message says what happened and, where it can,
what to do instead.
"""

from __future__ import annotations


class FxError(Exception):
    """An error we can describe to the caller without inventing a number."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def body(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}
