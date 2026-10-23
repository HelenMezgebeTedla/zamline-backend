class DomainError(Exception):
    pass


class NotFoundError(DomainError):
    pass


class NotAllowedError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ExternalServiceError(DomainError):
    pass
