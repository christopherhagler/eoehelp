"""Application exceptions and their HTTP mapping.

Messages here are returned to clients, so they must never disclose whether a
record exists or whose it is.
"""

from fastapi import HTTPException, status


class AppError(HTTPException):
    pass


class NotFoundError(AppError):
    """Used for both missing and not-owned resources.

    Always 404, never 403: a 403 on another patient's record would confirm that
    the record exists, which is itself a disclosure.
    """

    def __init__(self, detail: str = "Not found") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class BadRequestError(AppError):
    """A request the client can correct, described without disclosing anything."""

    def __init__(self, detail: str = "That request could not be processed.") -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class UnauthenticatedError(AppError):
    def __init__(self, detail: str = "Not authenticated") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenError(AppError):
    def __init__(self, detail: str = "Not permitted") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class InvalidTokenError(AppError):
    def __init__(self, detail: str = "This link is invalid or has expired.") -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ConflictError(AppError):
    def __init__(self, detail: str = "Conflict") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)
