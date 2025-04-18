#!/usr/bin/env python3
import secrets, base64, pathlib

key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
print(key)

env = pathlib.Path('.env')
if env.exists():
    env.write_text(env.read_text() + f'\nJWT_SECRET={key}\n')
