import os
import jwt
from fastapi import Depends, Header, HTTPException, status

async def verify_token(authorization: str = Header()):
    """
    Проверяет, что в Header Authorization передан валидный JWT.
    Секрет берётся из среды каждый вызов, чтобы тесты и runtime использовали актуальное значение.
    """
    if not authorization.startswith('Bearer '):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Bad auth header')
    token = authorization.split()[1]

    # Считываем секрет здесь, а не при импорте модуля
    secret = os.getenv('JWT_SECRET', 'dev_secret')

    try:
        jwt.decode(token, secret, algorithms=['HS256'])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Invalid token')
