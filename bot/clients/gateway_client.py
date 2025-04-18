import os, aiohttp, jwt, datetime

class GatewayClient:
    def __init__(self):
        self.base = os.getenv('GATEWAY_URL', 'http://localhost:8000/v1')
        secret = os.getenv('JWT_SECRET', 'dev_secret')
        exp = datetime.datetime.now() + datetime.timedelta(hours=1)
        self.token = jwt.encode({'exp': exp}, secret, algorithm='HS256')

    async def post(self, path: str, json: dict):
        headers = {'Authorization': f'Bearer {self.token}'}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(f'{self.base}{path}', json=json, timeout=10) as resp:
                return await resp.json()
