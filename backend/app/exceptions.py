from fastapi import Request
from fastapi.responses import JSONResponse

class AppError(Exception):
    def __init__(self, code: int, message: str, detail: str = None, status_code: int = 400):
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code

async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "detail": exc.detail},
    )
