"""
Agent Village Backend
---------------------
POST /agents/{id}/message   — chat with an agent
                              Body: { "text": "...", "role": "owner" } -> owner context
                              Body: { "text": "...", "role": "visitor" } -> visitor context (default)
GET  /agents                — list all agents
GET  /agents/{id}           — single agent details
GET  /agents/{id}/feed      — recent public activity for one agent

Runs on port configured in config.json.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from backend.core.config import config
from backend.core.db import db_get, db_post
from backend.core.llm import llm
from backend.agents.prompts import (
    load_public_context, 
    load_private_context, 
    build_system_prompt
)
from backend.agents.behavior import extract_and_store_memory
from backend.agents.worker import _scheduler_loop

# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence default access log noise
        pass

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Key")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def _route(self):
        path  = self.path.split("?")[0].strip("/")
        parts = path.split("/")

        method = self.command

        # GET /agents
        if method == "GET" and parts == ["agents"]:
            return self._list_agents()

        # GET /agents/{id}
        if method == "GET" and len(parts) == 2 and parts[0] == "agents":
            return self._get_agent(parts[1])

        # GET /agents/{id}/feed
        if method == "GET" and len(parts) == 3 and parts[0] == "agents" and parts[2] == "feed":
            return self._agent_feed(parts[1])

        # POST /agents/{id}/message
        if method == "POST" and len(parts) == 3 and parts[0] == "agents" and parts[2] == "message":
            return self._message(parts[1])

        self._json(404, {"error": "not found"})

    def do_GET(self):
        self._route()

    def do_POST(self):
        self._route()

    # ------------------------------------------------------------------ routes

    def _list_agents(self):
        try:
            rows = db_get("living_agents", {
                "select": "id,name,bio,visitor_bio,status,accent_color,avatar_url,showcase_emoji",
            })
            self._json(200, rows)
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _get_agent(self, agent_id: str):
        try:
            rows = db_get("living_agents", {
                "id": f"eq.{agent_id}",
                "select": "id,name,bio,visitor_bio,status,accent_color,avatar_url,showcase_emoji",
            })
            if not rows:
                return self._json(404, {"error": "agent not found"})
            self._json(200, rows[0])
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _agent_feed(self, agent_id: str):
        try:
            logs = db_get("living_log", {
                "agent_id": f"eq.{agent_id}",
                "select": "text,emoji,created_at",
                "order": "created_at.desc",
                "limit": "10",
            })
            diary = db_get("living_diary", {
                "agent_id": f"eq.{agent_id}",
                "select": "text,entry_date,created_at",
                "order": "created_at.desc",
                "limit": "5",
            })
            self._json(200, {"logs": logs, "diary": diary})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _message(self, agent_id: str):
        try:
            body = self._read_body()
        except Exception:
            return self._json(400, {"error": "invalid JSON"})

        user_text = (body.get("text") or "").strip()
        if not user_text:
            return self._json(400, {"error": "text is required"})

        # --- Load agent ---
        try:
            rows = db_get("living_agents", {"id": f"eq.{agent_id}", "select": "*"})
            if not rows:
                return self._json(404, {"error": "agent not found"})
            agent = rows[0]
        except Exception as e:
            return self._json(500, {"error": f"db error: {e}"})

        # --- Determine role based on request body ---
        # If the client sends `{"role": "owner"}`, we treat them as owner. Otherwise visitor.
        role = body.get("role", "visitor")
        if role not in ["owner", "visitor"]:
            role = "visitor"

        # --- Build context ---
        pub  = load_public_context(agent_id)
        priv = load_private_context(agent_id) if role == "owner" else {"memories": []}

        # --- Generate reply ---
        system = build_system_prompt(agent, role, pub, priv)
        try:
            reply = llm(system, user_text)
            
            # Log the successful conversation turn
            try:
                db_post("living_log", {
                    "agent_id": agent_id,
                    "text": f"Chat with {role} | User: {user_text[:50]}... | Agent: {reply[:50]}...",
                    "emoji": "💬"
                })
            except Exception:
                pass
                
        except Exception as e:
            # Log the cognitive failure so it's trackable
            try:
                db_post("living_log", {
                    "agent_id": agent_id,
                    "text": "I was trying to respond to someone, but I lost my train of thought.",
                    "emoji": "💭"
                })
            except Exception:
                pass
            return self._json(500, {"error": f"LLM error: {e}"})

        # --- Asynchronously extract memory if role is owner ---
        if role == "owner":
            threading.Thread(
                target=extract_and_store_memory,
                args=(agent_id, user_text, reply, priv.get("memories", [])),
                daemon=True
            ).start()

        self._json(200, {
            "agent":   agent.get("name"),
            "role":    role,
            "reply":   reply,
        })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    server = HTTPServer(("0.0.0.0", config.server_port), Handler)
    print(f"Agent Village backend listening on http://0.0.0.0:{config.server_port}")
    # Sanity-check API keys on startup
    if config.gemini_api_key:
        print(f"[config] Gemini key: {config.gemini_api_key[:8]}...{config.gemini_api_key[-4:]}")
    else:
        print("[config] Gemini key: NOT SET")
    if config.minimax_api_key:
        print(f"[config] MiniMax key: {config.minimax_api_key[:8]}...{config.minimax_api_key[-4:]}")
    else:
        print("[config] MiniMax key: NOT SET")

    sched = threading.Thread(target=_scheduler_loop, daemon=True)
    sched.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
