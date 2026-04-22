from http.server import BaseHTTPRequestHandler
import json, urllib.request
from urllib.parse import urlparse, parse_qs

# Aave V3 usa GraphQL via API publica do Aave
AAVE_GRAPHQL = 'https://api.thegraph.com/subgraphs/name/aave/protocol-v3'

AAVE_QUERY = '''
{
  userReserves(where: {user: "%s"}) {
    currentATokenBalance
    currentVariableDebt
    currentStableDebt
    reserve {
      symbol
      name
      decimals
      liquidityRate
      variableBorrowRate
      price { priceInEth }
      underlyingAsset
    }
    user { healthFactor }
  }
}
'''

ETH_PRICE_URL = 'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd'

def fetch(url, data=None, headers={}, timeout=9):
    try:
        req = urllib.request.Request(url, data=data, headers=headers)
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

        # Testa GraphQL do Aave
        query = AAVE_QUERY % address.lower()
        payload = json.dumps({'query': query}).encode()
        result = fetch(
            AAVE_GRAPHQL,
            data=payload,
            headers={'Content-Type': 'application/json'}
        )
        self.wfile.write(json.dumps({'graphql_result': result}).encode())

    def log_message(self, *a): pass
