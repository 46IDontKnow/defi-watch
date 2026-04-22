from http.server import BaseHTTPRequestHandler
import json, urllib.request, concurrent.futures
from urllib.parse import urlparse, parse_qs
 
MORALIS_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImVlMWZmOGZkLTNlMDEtNDhiNy04OTFhLThkMTY2MjQxMDFkYiIsIm9yZ0lkIjoiNTExNzkxIiwidXNlcklkIjoiNTI2NjIxIiwidHlwZUlkIjoiYTM4N2Y1YTQtMTI5Ni00OGRkLTllNGMtMDM4OWEzNzM0ZGMwIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NzY4Nzg3MjQsImV4cCI6NDkzMjYzODcyNH0.CDSfO1NgH6lrfjAycyCcZlClhns8hu3hyjo-a75Y6Kc'
MORALIS_BASE = 'https://deep-index.moralis.io/api/v2.2'
 
AAVE_POOLS = {
    'eth':   '0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e',
    'matic': '0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb',
    'base':  '0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64B',
}
CHAIN_IDS   = {'eth':'0x1','base':'0x2105','matic':'0x89','bsc':'0x38'}
NATIVE_SYM  = {'eth':'ETH','base':'ETH','matic':'MATIC','bsc':'BNB'}
NATIVE_NAME = {'eth':'Ethereum','base':'Ethereum','matic':'Polygon','bsc':'BNB Chain'}
 
def fetch_url(url, headers={}, timeout=8):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return None
 
def get_prices():
    d = fetch_url('https://api.coingecko.com/api/v3/simple/price?ids=ethereum,matic-network,binancecoin&vs_currencies=usd', timeout=5)
    if not d: return {'eth':3500,'matic':0.8,'bsc':600}
    return {
        'eth':   d.get('ethereum',{}).get('usd',3500),
        'matic': d.get('matic-network',{}).get('usd',0.8),
        'bsc':   d.get('binancecoin',{}).get('usd',600),
    }
 
def moralis(path, timeout=7):
    return fetch_url(MORALIS_BASE+path, {'X-API-Key':MORALIS_KEY,'accept':'application/json'}, timeout=timeout)
 
def get_chain_data(address, chain, prices):
    """Busca tokens nativos + ERC20 + Aave para uma chain"""
    chain_id = CHAIN_IDS.get(chain,'0x1')
    tokens = []
 
    # Token nativo
    native = moralis(f'/{address}/balance?chain={chain_id}')
    if native:
        bal = int(native.get('balance',0))/1e18
        price = prices.get('matic' if chain=='matic' else ('bsc' if chain=='bsc' else 'eth'))
        if bal > 0.0001:
            tokens.append({
                'symbol':NATIVE_SYM.get(chain,'ETH'),
                'name':NATIVE_NAME.get(chain,'Ethereum'),
                'balance':round(bal,6),'usd':round(bal*price,2),
                'chain':chain,'logo':None,'source':'wallet'
            })
 
    # ERC20 tokens
    erc20 = moralis(f'/{address}/erc20?chain={chain_id}&limit=30')
    if erc20:
        for t in (erc20.get('result') or []):
            try:
                dec = int(t.get('decimals') or 18)
                bal = int(t.get('balance',0))/(10**dec)
                if bal < 0.000001: continue
                pd = moralis(f'/erc20/{t["token_address"]}/price?chain={chain_id}', timeout=5)
                if not pd: continue
                usd = bal*(pd.get('usdPrice') or 0)
                if usd < 0.5: continue
                tokens.append({
                    'symbol':t.get('symbol','?'),'name':t.get('name','?'),
                    'balance':round(bal,6),'usd':round(usd,2),
                    'chain':chain,'logo':t.get('thumbnail') or t.get('logo'),
                    'source':'wallet'
                })
            except: continue
 
    # Aave V3
    supplies, borrows, hf = [], [], 99
    pool_id = AAVE_POOLS.get(chain)
    if pool_id:
        data = fetch_url(f'https://aave-api-v2.aave.com/data/users/{address.lower()}?poolId={pool_id}', timeout=8)
        if data and 'userReserves' in data:
            for ur in data.get('userReserves',[]):
                res = ur.get('reserve',{})
                dec = int(res.get('decimals') or 18)
                price_usd = float(res.get('priceInUSD') or 0)
                sup = float(ur.get('scaledATokenBalance') or ur.get('currentATokenBalance') or 0)/(10**dec)
                debt = (float(ur.get('scaledVariableDebt') or ur.get('currentVariableDebt') or 0) +
                        float(ur.get('principalStableDebt') or ur.get('currentStableDebt') or 0))/(10**dec)
                if sup > 0.000001 and price_usd > 0:
                    usd = sup*price_usd
                    if usd > 0.1:
                        supplies.append({
                            'symbol':res.get('symbol','?'),'name':res.get('name','?'),
                            'balance':round(sup,6),'usd':round(usd,2),
                            'chain':chain,'logo':None,'source':'aave',
                            'apy':round((float(res.get('liquidityRate') or 0)/1e27)*100,4)
                        })
                if debt > 0.000001 and price_usd > 0:
                    usd = debt*price_usd
                    if usd > 0.1:
                        borrows.append({
                            'symbol':res.get('symbol','?'),'name':res.get('name','?'),
                            'balance':round(debt,6),'usd':round(usd,2),
                            'chain':chain,'logo':None,'source':'aave','protocol':'Aave V3',
                            'apy':round((float(res.get('variableBorrowRate') or 0)/1e27)*100,4)
                        })
            hf_raw = float(data.get('healthFactor') or data.get('currentHealthFactor') or 0)
            hf = 99 if (not hf_raw or hf_raw > 1e15) else round(hf_raw,2)
 
    return {
        'chain':   chain,
        'tokens':  tokens,
        'supplies': supplies,
        'borrows':  borrows,
        'hf':       hf,
    }
 
def fetch_wallet(address, label):
    prices = get_prices()
    chains = ['eth','base','matic','bsc']
 
    # Busca todas as chains em paralelo (mais rápido)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(get_chain_data, address, c, prices): c for c in chains}
        for f in concurrent.futures.as_completed(futures, timeout=25):
            try: results.append(f.result())
            except: pass
 
    all_tokens   = [t for r in results for t in r.get('tokens',[])]
    all_supplies = [t for r in results for t in r.get('supplies',[])]
    all_borrows  = [t for r in results for t in r.get('borrows',[])]
 
    hfs = [r['hf'] for r in results if r.get('borrows') and r['hf'] < 99]
    min_hf = min(hfs) if hfs else 99
 
    assets = sorted(all_tokens + all_supplies, key=lambda x: x['usd'], reverse=True)
    liabilities = sorted(all_borrows, key=lambda x: x['usd'], reverse=True)
 
    return {
        'label':       label,
        'address':     address,
        'assets':      assets,
        'liabilities': liabilities,
        'healthFactor':min_hf,
        'error':       None,
    }
 
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params  = parse_qs(urlparse(self.path).query)
        address = params.get('address',[None])[0]
        label   = params.get('label',['Carteira'])[0]
 
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Access-Control-Allow-Origin','*')
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
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
 
    def log_message(self,*a): pass
