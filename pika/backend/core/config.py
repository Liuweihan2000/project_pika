import os
import json
from pathlib import Path

# Config file is located in the same directory as the backend module
CONFIG_PATH = Path(__file__).parent.parent / "config.json"

class Config:
    def __init__(self, config_dict: dict):
        self._config = config_dict
        
        self.server_port = int(os.getenv("PORT", self._config.get("server", {}).get("port", 8787)))
        
        db = self._config.get("database", {})
        self.supabase_rest_url = os.getenv("SUPABASE_REST_URL", db.get("supabase_rest_url", ""))
        self.supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", db.get("supabase_anon_key", ""))
        self.supabase_svc_key = os.getenv("SUPABASE_SERVICE_KEY", db.get("supabase_svc_key", ""))
        self.db_timeout = int(db.get("timeout", 15))
        
        llm = self._config.get("llm", {})
        gemini = llm.get("gemini", {})
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", gemini.get("api_key", ""))
        self.gemini_model = os.getenv("GEMINI_MODEL", gemini.get("model", "v1beta/models/gemini-2.0-flash:generateContent"))
        
        minimax = llm.get("minimax", {})
        self.minimax_api_key = os.getenv("MINIMAX_API_KEY", minimax.get("api_key", ""))
        self.minimax_model = os.getenv("MINIMAX_MODEL", minimax.get("model", "MiniMax-M2.1-highspeed"))
        
        self.llm_rate_limit_rpm = int(llm.get("rate_limit_rpm", 12))
        self.llm_timeout = int(llm.get("timeout", 30))
        
        agent = self._config.get("agent", {})
        self.agent_startup_stagger_min = float(agent.get("startup_stagger_min", 0.0))
        self.agent_startup_stagger_max = float(agent.get("startup_stagger_max", 15.0))
        self.agent_loop_interval_min = float(agent.get("loop_interval_min", 8.0))
        self.agent_loop_interval_max = float(agent.get("loop_interval_max", 12.0))
        self.agent_missing_sleep = float(agent.get("missing_agent_sleep", 15.0))
        self.agent_scheduler_interval = float(agent.get("scheduler_interval", 20.0))

def load_config() -> Config:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[config] Failed to load {CONFIG_PATH}, using defaults or env vars. Error: {e}")
        data = {}
    return Config(data)

config = load_config()
