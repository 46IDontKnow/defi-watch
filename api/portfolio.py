from http.server import BaseHTTPRequestHandler
import json, urllib.request
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

def fetch_url(url, headers={}):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except: return None

def get_prices():
    d = fetch_url('https://api.coingecko.com/api/v3/simple/price?ids=ethereum,matic-network,binancecoin&vs_currencies=usd')
    if not d: return {'eth':3500,'matic':0.8,'bsc':600}
    return {'eth':d.get('ethereum',{}).get('usd',3500),'matic':d.get('matic-network',{}).get('usd',0.8),'bsc':d.get('binancecoin',{}).get('usd',600)}

def moralis(path):
    return fetch_url(MORALIS_BASE+path, {'X-API-Key':MORALIS_KEY,'accept':'application/json'})

def get_wallet_tokens(address, chain, prices):
    chain_id = CHAIN_IDS.get(chain,'0x1')
    tokens = []
    native = moralis(f'/{address}/balance?chain={chain_id}')
    if native:
        bal = int(native.get('balance',0))/1e18
        price = prices.get('matic' if chain=='matic' else ('bsc' if chain=='bsc' else 'eth'))
        if bal > 0.0001:
            tokens.append({'symbol':NATIVE_SYM.get(chain,'ETH'),'name':NATIVE_NAME.get(chain,'Ethereum'),'balance':bal,'usd':bal*price,'chain':chain,'logo':None,'source':'wallet'})
    erc20 = moralis(f'/{address}/erc20?chain={chain_id}&limit=50')
    for t in (erc20 or {}).get('result',[]):
        dec = int(t.get('decimals') or 18)
        bal = int(t.get('balance',0))/(10**dec)
        if bal < 0.000001: continue
        pd = moralis(f'/erc20/{t["token_address"]}/price?chain={chain_id}')
        if not pd: continue
        usd = bal*(pd.get('usdPrice') or 0)
        if usd < 0.5: continue
        tokens.append({'symbol':t.get('symbol','?'),'name':t.get('name','?'),'balance':bal,'usd':usd,'chain':chain,'logo':t.get('thumbnail') or t.get('logo'),'source':'wallet'})
    return sorted(tokens, key=lambda x:x['usd'], reverse=True)

def get_aave(address, chain):
    pool_id = AAVE_POOLS.get(chain)
    if not pool_id: return {'supplies':[],'borrows':[],'healthFactor':99}
    data = fetch_url(f'https://aave-api-v2.aave.com/data/users/{address.lower()}?poolId={pool_id}')
    if not data or 'userReserves' not in data: return {'supplies':[],'borrows':[],'healthFactor':99}
    supplies, borrows = [], []
    for ur in data.get('userReserves',[]):
        res = ur.get('reserve',{})
        dec = int(res.get('decimals') or 18)
        price = float(res.get('priceInUSD') or 0)
        sup = float(ur.get('scaledATokenBalance') or ur.get('currentATokenBalance') or 0)/(10**dec)
        debt = (float(ur.get('scaledVariableDebt') or ur.get('currentVariableDebt') or 0) +
                float(ur.get('principalStableDebt') or ur.get('currentStableDebt') or 0))/(10**dec)
        if sup > 0.000001 and price > 0:
            usd = sup*price
            if usd > 0.1: supplies.append({'symbol':res.get('symbol','?'),'name':res.get('name','?'),'balance':sup,'usd':usd,'chain':chain,'logo':None,'source':'aave','apy':(float(res.get('liquidityRate') or 0)/1e27)*100})
        if debt > 0.000001 and price > 0:
            usd = debt*price
            if usd > 0.1: borrows.append({'symbol':res.get('symbol','?'),'name':res.get('name','?'),'balance':debt,'usd':usd,'chain':chain,'logo':None,'source':'aave','protocol':'Aave V3','apy':(float(res.get('variableBorrowRate') or 0)/1e27)*100})
    hf_raw = float(data.get('healthFactor') or data.get('currentHealthFactor') or 0)
    hf = 99 if (not hf_raw or hf_raw > 1e15) else round(hf_raw,2)
    return {'supplies':supplies,'borrows':borrows,'healthFactor':hf}

def fetch_wallet(address, label):
    prices = get_prices()
    all_tokens, all_supplies, all_borrows, min_hf = [], [], [], 99
    for chain in ['eth','base','matic','bsc']:
        all_tokens.extend(get_wallet_tokens(address, chain, prices))
        if chain in AAVE_POOLS:
            av = get_aave(address, chain)
            all_supplies.extend(av['supplies'])
            all_borrows.extend(av['borrows'])
            if av['borrows'] and av['healthFactor'] < min_hf:
                min_hf = av['healthFactor']
    assets = sorted(all_tokens+all_supplies, key=lambda x:x['usd'], reverse=True)
    liabilities = sorted(all_borrows, key=lambda x:x['usd'], reverse=True)
    return {'label':label,'address':address,'assets':assets,'liabilities':liabilities,'healthFactor':min_hf,'error':None}

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
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
            self.wfile.write(json.dumps(fetch_wallet(address, label)).encode())
        except Exception as e:
            self.wfile.write(json.dumps({'error':str(e)}).encode())
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
    def log_message(self,*a): pass
