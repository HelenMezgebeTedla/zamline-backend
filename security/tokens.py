import os
import jwt
from fastapi import HTTPException, status

SECRET_KEY = os.getenv("SECRET_KEY", "secretkey")
ALGORITHM = os.getenv("ALGORITHM", "HS256")


def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
