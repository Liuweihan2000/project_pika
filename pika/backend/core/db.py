import json
from urllib import request as urlrequest, parse
from backend.core.config import config

_READ_HEADERS = {
    "apikey": config.supabase_anon_key,
    "Authorization": f"Bearer {config.supabase_anon_key}",
    "Content-Type": "application/json",
}

_WRITE_HEADERS = {
    "apikey": config.supabase_svc_key or config.supabase_anon_key,
    "Authorization": f"Bearer {config.supabase_svc_key or config.supabase_anon_key}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

def db_get(table: str, params: dict) -> list:
    url = f"{config.supabase_rest_url}/{table}?" + parse.urlencode(params)
    req = urlrequest.Request(url, headers=_READ_HEADERS, method="GET")
    with urlrequest.urlopen(req, timeout=config.db_timeout) as r:
        return json.loads(r.read().decode())

def db_post(table: str, payload: dict) -> None:
    url = f"{config.supabase_rest_url}/{table}"
    data = json.dumps(payload).encode()
    req = urlrequest.Request(url, data=data, headers=_WRITE_HEADERS, method="POST")
    with urlrequest.urlopen(req, timeout=config.db_timeout) as r:
        r.read()

def db_patch(table: str, match: dict, payload: dict) -> None:
    qs = parse.urlencode({k: f"eq.{v}" for k, v in match.items()})
    url = f"{config.supabase_rest_url}/{table}?{qs}"
    data = json.dumps(payload).encode()
    req = urlrequest.Request(url, data=data, headers=_WRITE_HEADERS, method="PATCH")
    with urlrequest.urlopen(req, timeout=config.db_timeout) as r:
        r.read()
