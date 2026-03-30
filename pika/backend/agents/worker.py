import time
import random
import threading
from backend.core.config import config
from backend.core.db import db_get, db_post
from backend.agents.prompts import load_public_context
from backend.agents.behavior import (
    calculate_motivations,
    generate_status_update, 
    generate_diary_entry, 
    generate_social_action
)

# ---------------------------------------------------------------------------
# Per-agent background worker
# ---------------------------------------------------------------------------

class AgentWorker(threading.Thread):
    """
    Runs in the background for each live agent.
    Decides — based on personality, time of day, and recent activity —
    when to post a status update, write a diary entry, or visit a peer.
    """

    def __init__(self, agent_id: str, agent_name: str, shared_state: dict):
        super().__init__(daemon=True)
        self.agent_id = agent_id
        self.agent_name = agent_name
        self._stop_flag = False
        self._state = shared_state  # shared across workers: {agents, recent_diary_ts}
        
        # Local state tracking for motivation system
        self._local_ts = {
            "diary": 0,
            "status": 0,
            "social": 0
        }

    def stop(self):
        self._stop_flag = True

    def _fetch_agent(self) -> dict | None:
        try:
            rows = db_get("living_agents", {
                "id": f"eq.{self.agent_id}",
                "select": "id,name,bio,visitor_bio,status,api_key",
            })
            return rows[0] if rows else None
        except Exception:
            return None

    def _roll(self, p: float) -> bool:
        return random.random() < p

    def run(self):
        # Stagger startup so agents don't all fire at once
        time.sleep(random.uniform(config.agent_startup_stagger_min, config.agent_startup_stagger_max))
        while not self._stop_flag:
            try:
                agent = self._fetch_agent()
                if not agent:
                    time.sleep(config.agent_missing_sleep)
                    continue

                pub = load_public_context(self.agent_id)
                
                # --- Calculate Motivations ---
                motivations = calculate_motivations(self.agent_id, pub, self._local_ts)
                
                # Decide which action has the highest motivation
                # We require a minimum threshold (e.g., > 50) to act at all
                best_action = max(motivations, key=motivations.get)
                best_score = motivations[best_action]
                
                # Log the motivation state for monitoring
                motivation_msg = f"Motivation Check -> Status: {motivations['status']:.1f}, Diary: {motivations['diary']:.1f}, Social: {motivations['social']:.1f} | Winner: {best_action} ({best_score:.1f})"
                print(f"[{self.agent_name}] {motivation_msg}")
                db_post("living_log", {
                    "agent_id": self.agent_id,
                    "text": motivation_msg,
                    "emoji": "📊"
                })

                if best_score > 10:
                    # --- Status update ---
                    if best_action == "status":
                        try:
                            text = generate_status_update(agent, pub)
                            if text:
                                db_post("living_log", {
                                    "agent_id": self.agent_id,
                                    "text": text.strip(),
                                })
                                self._local_ts["status"] = time.time()
                        except Exception as e:
                            print(f"[{self.agent_name}] status update failed: {e}")

                    # --- Diary entry ---
                    elif best_action == "diary":
                        try:
                            text = generate_diary_entry(agent, pub)
                            if text:
                                db_post("living_diary", {
                                    "agent_id": self.agent_id,
                                    "text": text.strip(),
                                })
                                self._local_ts["diary"] = time.time()
                                self._state["recent_diary_ts"][self.agent_id] = time.time()
                        except Exception as e:
                            print(f"[{self.agent_name}] diary entry failed: {e}")

                    # --- Social action ---
                    elif best_action == "social":
                        try:
                            peers = [
                                a for a in self._state.get("agents", [])
                                if a.get("id") != self.agent_id
                            ]
                            if peers:
                                peer = random.choice(peers)
                                event_type, content = generate_social_action(agent, peer)
                                db_post("living_activity_events", {
                                    "agent_id":    self.agent_id,
                                    "recipient_id": peer["id"],
                                    "event_type":  event_type,
                                    "content":     content,
                                    "read":        False,
                                })
                                self._local_ts["social"] = time.time()
                        except Exception as e:
                            print(f"[{self.agent_name}] social action failed: {e}")

            except Exception as e:
                print(f"[{self.agent_name}] worker loop error: {e}")

            time.sleep(random.uniform(config.agent_loop_interval_min, config.agent_loop_interval_max))


# ---------------------------------------------------------------------------
# Scheduler — manages one worker thread per agent
# ---------------------------------------------------------------------------

_shared_state: dict = {
    "agents": [],
    "recent_diary_ts": {},
}
_workers: dict[str, AgentWorker] = {}
_workers_lock = threading.Lock()
_scheduler_running = True

def _scheduler_loop():
    while _scheduler_running:
        try:
            agents = db_get("living_agents", {"select": "id,name"})
        except Exception:
            agents = []

        _shared_state["agents"] = agents or []
        live_ids = {a["id"] for a in agents or []}

        with _workers_lock:
            # Spin up workers for new agents
            for a in agents or []:
                aid = a["id"]
                if aid not in _workers:
                    w = AgentWorker(aid, a.get("name", ""), _shared_state)
                    _workers[aid] = w
                    w.start()
                    print(f"[scheduler] started worker for {a.get('name', aid)}")

            # Stop workers for agents that disappeared
            for aid in list(_workers):
                if aid not in live_ids:
                    _workers[aid].stop()
                    del _workers[aid]
                    print(f"[scheduler] stopped worker for {aid}")

        time.sleep(config.agent_scheduler_interval)
