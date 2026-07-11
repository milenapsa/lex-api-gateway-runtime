from __future__ import annotations
import hmac, json, os, time, urllib.request, urllib.error, urllib.parse
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT=int(os.getenv("PORT","8090"))
UPSTREAM=os.getenv("LEX_UPSTREAM","http://homosapiens-lex-search-core-v51:8080")
DEMO_LIMIT=int(os.getenv("LEX_DEMO_REQUESTS_PER_HOUR","20"))
COMM_LIMIT=int(os.getenv("LEX_COMMERCIAL_REQUESTS_PER_MINUTE","120"))
API_KEY=os.getenv("LEX_API_KEY","").strip()
buckets=defaultdict(deque)

def allow(key, cap, window):
    now=time.monotonic(); q=buckets[key]
    while q and q[0] <= now-window: q.popleft()
    if len(q)>=cap: return False,0,max(1,int(window-(now-q[0])))
    q.append(now); return True,cap-len(q),0

def call_upstream(path, body):
    req=urllib.request.Request(UPSTREAM+path,data=body,headers={"Content-Type":"application/json","User-Agent":"LexGateway/0.8"},method="POST")
    with urllib.request.urlopen(req,timeout=20) as r:
        return r.status,r.read(),dict(r.headers)

class H(BaseHTTPRequestHandler):
    server_version="LexGateway/0.8"
    def sendj(self,status,obj,headers=None):
        data=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        for k,v in (headers or {}).items(): self.send_header(k,str(v))
        self.end_headers(); self.wfile.write(data)
    def ip(self):
        return self.headers.get("X-Forwarded-For",self.client_address[0]).split(",")[0].strip()
    def key(self):
        k=self.headers.get("X-API-Key","").strip()
        if k:return k
        a=self.headers.get("Authorization","")
        return a[7:].strip() if a.lower().startswith("bearer ") else ""
    def read(self):
        n=int(self.headers.get("Content-Length","0") or 0)
        if n>64000: raise ValueError("payload_too_large")
        return self.rfile.read(n)
    def do_GET(self):
        p=urllib.parse.urlparse(self.path).path
        if p=="/health":
            self.sendj(200,{"status":"ok","service":"lex-api-gateway","version":"0.8.0-pilot","demo_limit_per_hour":DEMO_LIMIT,"commercial_limit_per_minute":COMM_LIMIT,"commercial_auth":"configured" if API_KEY else "not_configured"})
        elif p=="/v1/readiness":
            self.sendj(200,{"status":"ready","demo":True,"commercial":bool(API_KEY),"upstream":UPSTREAM})
        else:self.sendj(404,{"error":"not_found"})
    def do_POST(self):
        p=urllib.parse.urlparse(self.path).path
        demo=p=="/v1/search/demo"
        commercial=p in {"/v1/search","/v1/search/global","/v1/search/legislacao","/v1/search/datasets"}
        if not demo and not commercial:return self.sendj(404,{"error":"not_found"})
        if demo:
            ok,remaining,retry=allow("demo:"+self.ip(),DEMO_LIMIT,3600)
            if not ok:return self.sendj(429,{"error":"demo_rate_limit_exceeded","retry_after_seconds":retry},{"Retry-After":retry})
            target="/v1/search"; tier="public_demo"; cap=5
        else:
            if not API_KEY:return self.sendj(503,{"error":"commercial_auth_not_configured"})
            presented=self.key()
            if not presented or not hmac.compare_digest(presented,API_KEY):return self.sendj(401,{"error":"invalid_api_key"})
            ok,remaining,retry=allow("commercial",COMM_LIMIT,60)
            if not ok:return self.sendj(429,{"error":"commercial_rate_limit_exceeded","retry_after_seconds":retry},{"Retry-After":retry})
            target=p; tier="commercial_pilot"; cap=20
        try:
            raw=self.read(); payload=json.loads(raw or b"{}")
            if not str(payload.get("query") or payload.get("q") or "").strip():return self.sendj(422,{"error":"query_required"})
            payload["limit"]=min(max(1,int(payload.get("limit",10))),cap)
            status,body,_=call_upstream(target,json.dumps(payload,ensure_ascii=False).encode())
            data=json.loads(body.decode()); data["access_tier"]=tier
            self.sendj(status,data,{"X-RateLimit-Limit":DEMO_LIMIT if demo else COMM_LIMIT,"X-RateLimit-Remaining":remaining})
        except ValueError as e:self.sendj(400,{"error":str(e)})
        except (urllib.error.URLError,TimeoutError) as e:self.sendj(502,{"error":"upstream_unavailable","detail":str(e)[:160]})
        except Exception as e:self.sendj(500,{"error":"gateway_error","detail":e.__class__.__name__})
    def log_message(self,fmt,*args):
        print(json.dumps({"time":time.time(),"client":self.ip(),"method":self.command,"path":urllib.parse.urlparse(self.path).path,"message":fmt%args}),flush=True)

ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
