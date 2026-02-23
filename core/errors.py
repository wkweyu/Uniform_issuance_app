class AppError(Exception):
    """Base error class for the application."""
    def __init__(self, message, status_code=400, payload=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload

class ValidationError(AppError):
    """Raised when input validation fails."""
    pass

class AuthenticationError(AppError):
    """Raised when authentication fails."""
    def __init__(self, message="Authentication required", status_code=401, payload=None):
        super().__init__(message, status_code, payload)

class ForbiddenError(AppError):
    """Raised when access is denied."""
    def __init__(self, message="Access denied", status_code=403, payload=None):
        super().__init__(message, status_code, payload)

class NotFoundError(AppError):
    """Raised when a resource is not found."""
    def __init__(self, message="Resource not found", status_code=404, payload=None):
        super().__init__(message, status_code, payload)
