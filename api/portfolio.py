from http.server import BaseHTTPRequestHandler
import json, urllib.request
from urllib.parse import urlparse, parse_qs
 
AAVE_POOL_ETH = '0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e'
 
def fetch(url, timeout=9):
    try:
        req = urllib.request.Request(url, headers={'accept':'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {'_error': str(e)}
 
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params  = parse_qs(urlparse(self.path).query)
        address = params.get('address', [None])[0]
 
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
 
        if not address:
            self.wfile.write(json.dumps({'error':'address required'}).encode())
            return
 
        # Testa só o Aave ETH
        url = f'https://aave-api-v2.aave.com/data/users/{address.lower()}?poolId={AAVE_POOL_ETH}'
        result = fetch(url)
        self.wfile.write(json.dumps({'aave_raw': result}).encode())
 
    def log_message(self, *a): pass
