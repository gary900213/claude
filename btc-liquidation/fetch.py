import json, urllib.request, time, sys
B="https://www.okx.com/api/v5"
def get(u):
    for i in range(4):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"curl/8.5.0"}), timeout=15))
        except Exception as e:
            time.sleep(1+i)
    raise SystemExit("fail "+u)
out=sys.argv[1]
N=24*30
def pag(path, key="after"):
    rows=[]; cur=None
    while len(rows)<N:
        u=B+path+(f"&{key}={cur}" if cur else "")
        d=get(u)["data"]
        if not d: break
        rows+=d; cur=d[-1][0]; time.sleep(0.15)
    return rows
c=pag("/market/history-candles?instId=BTC-USDT-SWAP&bar=1H&limit=100")
o=pag("/rubik/stat/contracts/open-interest-history?instId=BTC-USDT-SWAP&period=1H&limit=100", key="end")
r=pag("/rubik/stat/contracts/long-short-account-ratio-contract?instId=BTC-USDT-SWAP&period=1H&limit=100", key="end")
json.dump({"candles":c,"oi":o,"ls":r}, open(out,"w"))
print(len(c),len(o),len(r), c[0][0], c[-1][0], o[-1][0], r[:1])
