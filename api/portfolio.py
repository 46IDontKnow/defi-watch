from http.server import BaseHTTPRequestHandler
import json, urllib.request, concurrent.futures
from urllib.parse import urlparse, parse_qs

AAVE_POOLS = {
    'eth':   '0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e',
    'matic': '0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb',
    'base':  '0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64B',
}

def fetch(url, headers={}, timeout=9):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return None

def get_prices():
    d = fetch('https://api.coingecko.com/api/v3/simple/price?ids=ethereum,matic-network,binancecoin&vs_currencies=usd', timeout=6)
    if not d: return {'eth':3500,'matic':0.8,'bsc':600}
    return {
        'eth':   d.get('ethereum',{}).get('usd',3500),
        'matic': d.get('matic-network',{}).get('usd',0.8),
        'bsc':   d.get('binancecoin',{}).get('usd',600),
    }

def get_aave(address, chain, prices):
    pool_id = AAVE_POOLS.get(chain)
    if not pool_id: return {'supplies':[], 'borrows':[], 'hf':99}

    data = fetch(f'https://aave-api-v2.aave.com/data/users/{address.lower()}?poolId={pool_id}')
    if not data or 'userReserves' not in data:
        return {'supplies':[], 'borrows':[], 'hf':99}

    supplies, borrows = [], []
    for ur in data.get('userReserves', []):
        res = ur.get('reserve', {})
        dec = int(res.get('decimals') or 18)
        price_usd = float(res.get('priceInUSD') or 0)

        sup  = float(ur.get('scaledATokenBalance') or ur.get('currentATokenBalance') or 0) / (10**dec)
        debt = (float(ur.get('scaledVariableDebt') or ur.get('currentVariableDebt') or 0) +
                float(ur.get('principalStableDebt') or ur.get('currentStableDebt') or 0)) / (10**dec)

        if sup > 0.000001 and price_usd > 0:
            usd = sup * price_usd
            if usd > 0.1:
                supplies.append({
                    'symbol':  res.get('symbol','?'),
                    'name':    res.get('name', res.get('symbol','?')),
                    'balance': round(sup, 6),
                    'usd':     round(usd, 2),
                    'chain':   chain,
                    'logo':    None,
                    'source':  'aave',
                    'apy':     round((float(res.get('liquidityRate') or 0)/1e27)*100, 4),
                })

        if debt > 0.000001 and price_usd > 0:
            usd = debt * price_usd
            if usd > 0.1:
                borrows.append({
                    'symbol':   res.get('symbol','?'),
                    'name':     res.get('name', res.get('symbol','?')),
                    'balance':  round(debt, 6),
                    'usd':      round(usd, 2),
                    'chain':    chain,
                    'logo':     None,
                    'source':   'aave',
                    'protocol': 'Aave V3',
                    'apy':      round((float(res.get('variableBorrowRate') or 0)/1e27)*100, 4),
                })

    hf_raw = float(data.get('healthFactor') or data.get('currentHealthFactor') or 0)
    hf = 99 if (not hf_raw or hf_raw > 1e15) else round(hf_raw, 2)
    return {'supplies': supplies, 'borrows': borrows, 'hf': hf}

def get_native(address, chain, prices):
    """Pega só saldo nativo via RPC público — sem Moralis"""
    rpc_urls = {
        'eth':   'https://eth.llamarpc.com',
        'base':  'https://base.llamarpc.com',
        'matic': 'https://polygon.llamarpc.com',
        'bsc':   'https://binance.llamarpc.com',
    }
    native_sym  = {'eth':'ETH','base':'ETH','matic':'MATIC','bsc':'BNB'}
    native_name = {'eth':'Ethereum','base':'Ethereum','matic':'Polygon','bsc':'BNB Chain'}

    url = rpc_urls.get(chain)
    if not url: return None

    payload = json.dumps({
        'jsonrpc':'2.0','id':1,
        'method':'eth_getBalance',
        'params':[address, 'latest']
    }).encode()

    try:
        req = urllib.request.Request(url, data=payload, headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=6) as r:
            resp = json.loads(r.read().decode())
            bal = int(resp.get('result','0x0'), 16) / 1e18
            price = prices.get('matic' if chain=='matic' else ('bsc' if chain=='bsc' else 'eth'), 3500)
            if bal > 0.0001:
                return {
                    'symbol':  native_sym.get(chain,'ETH'),
                    'name':    native_name.get(chain,'Ethereum'),
                    'balance': round(bal, 6),
                    'usd':     round(bal * price, 2),
                    'chain':   chain,
                    'logo':    None,
                    'source':  'wallet',
                }
    except: pass
    return None

def fetch_wallet(address, label):
    prices = get_prices()
    chains = ['eth', 'base', 'matic', 'bsc']
    aave_chains = ['eth', 'base', 'matic']

    all_supplies, all_borrows, all_natives = [], [], []
    min_hf = 99

    # Busca Aave e saldo nativo em paralelo
    def process_chain(chain):
        native = get_native(address, chain, prices)
        aave   = get_aave(address, chain, prices) if chain in aave_chains else {'supplies':[],'borrows':[],'hf':99}
        return chain, native, aave

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(process_chain, c) for c in chains]
        for f in concurrent.futures.as_completed(futures, timeout=28):
            try:
                chain, native, aave = f.result()
                if native: all_natives.append(native)
                all_supplies.extend(aave['supplies'])
                all_borrows.extend(aave['borrows'])
                if aave['borrows'] and aave['hf'] < min_hf:
                    min_hf = aave['hf']
            except: pass

    assets      = sorted(all_natives + all_supplies, key=lambda x: x['usd'], reverse=True)
    liabilities = sorted(all_borrows, key=lambda x: x['usd'], reverse=True)

    return {
        'label':        label,
        'address':      address,
        'assets':       assets,
        'liabilities':  liabilities,
        'healthFactor': min_hf,
        'error':        None,
    }

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params  = parse_qs(urlparse(self.path).query)
        address = params.get('address', [None])[0]
        label   = params.get('label',   ['Carteira'])[0]

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        if not address:
            self.wfile.write(json.dumps({'error':'address required'}).encode())
            return
        try:
            result = fetch_wallet(address, label)
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            self.wfile.write(json.dumps({'error':str(e),'assets':[],'liabilities':[],'healthFactor':99}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def log_message(self, *a): pass
