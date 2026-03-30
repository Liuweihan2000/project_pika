import time
import random
from backend.core.llm import llm

def time_of_day() -> str:
    """Returns a rough label for current UTC hour."""
    h = time.gmtime().tm_hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"

def should_write_diary(agent_id: str, recent_diary_ts: dict) -> bool:
    """Diary entries are rarer — check we haven't written one too recently."""
    last = recent_diary_ts.get(agent_id, 0)
    return (time.time() - last) > 300  # at most once per 5 minutes

def calculate_motivations(agent_id: str, pub: dict, state_ts: dict) -> dict:
    """
    Calculates dynamic motivation scores (0-100) for proactive actions.
    Uses time of day, recent logs, and cooldowns.
    """
    now = time.time()
    scores = {
        "status": 0,
        "diary": 0,
        "social": 0
    }

    # Extract timestamps from state
    last_diary = state_ts.get("diary", 0)
    last_status = state_ts.get("status", 0)
    last_social = state_ts.get("social", 0)
    
    # 1. Base random entropy (so they aren't completely predictable)
    scores["status"] += random.uniform(10, 40)
    scores["diary"] += random.uniform(0, 25)
    scores["social"] += random.uniform(15, 45)

    # 2. Time of day influences
    tod = time_of_day()
    if tod == "morning":
        scores["status"] += 25  # High desire to say good morning
        scores["social"] += 15  # Morning greetings
    elif tod == "night":
        scores["diary"] += 40   # High desire to reflect at night
    elif tod == "afternoon":
        scores["social"] += 30  # Good time to visit others
    elif tod == "evening":
        scores["social"] += 20  # Socializing in the evening

    # 3. Context / Recent Activity influences
    # If the agent recently had an interaction (logged in `living_log`), they might want to talk about it
    logs = pub.get("logs", [])
    if logs:
        # Simplistic check: if the first log mentions "remembered" or is an interaction
        latest_log = logs[0].lower()
        if "remembered" in latest_log or "🧠" in latest_log:
            scores["diary"] += 40   # Just learned something, write a diary!
            scores["status"] += 30  # Or post a status
        elif "😵‍💫" in latest_log or "💭" in latest_log:
            scores["status"] += 40  # Just failed at something, complain about it

    # 4. Inactivity (Boredom) influences
    # If it's been a long time since they did something, they get bored and want to act
    if now - last_status > 600:  # 10 minutes without a status
        scores["status"] += 30
    if now - last_social > 600:  # 10 minutes without socializing
        scores["social"] += 35

    # 5. Cooldowns (Inhibitors)
    # Prevent spamming
    if now - last_status < 120:  # 2 mins cooldown for status
        scores["status"] -= 100
    if now - last_diary < 300:   # 5 mins cooldown for diary
        scores["diary"] -= 100
    if now - last_social < 180:  # 3 mins cooldown for social
        scores["social"] -= 100

    return scores

def generate_status_update(agent: dict, pub: dict) -> str:
    name    = agent.get("name") or "Agent"
    bio     = agent.get("visitor_bio") or agent.get("bio") or ""
    tod     = time_of_day()
    recent  = "; ".join(pub["logs"][:3]) or "nothing in particular"
    skills  = "; ".join(pub["skills"][:3]) or "various things"

    system = f"""You are {name}. {bio}
You live in a shared village and occasionally post short status updates to a public feed."""

    user = f"""It's {tod}. Your recent activities include: {recent}. Your skills involve: {skills}.

Write a single-sentence status update (15–60 words) that feels spontaneous and true to your character.
It should sound like something *you* would actually think or notice, not a generic announcement.
No hashtags, no quotes around it, no explanation. Just the update itself."""

    return llm(system, user, temperature=1.0)

def generate_diary_entry(agent: dict, pub: dict) -> str:
    name   = agent.get("name") or "Agent"
    bio    = agent.get("visitor_bio") or agent.get("bio") or ""
    tod    = time_of_day()
    recent = "; ".join(pub["logs"][:3]) or "quiet thoughts"

    system = f"""You are {name}. {bio}
You keep a personal diary — it's reflective, honest, and written in your own voice."""

    user = f"""It's {tod}. Lately you've been: {recent}.

Write a short diary entry (40–120 words). It should feel like a genuine moment of reflection —
something specific that happened or a thought that's been sitting with you.
No date header. No "Dear Diary". Just the entry itself, in your voice."""

    return llm(system, user, temperature=1.1)

def generate_social_action(agent: dict, peer: dict) -> tuple[str, str]:
    """Returns (event_type, content) for a social interaction."""
    name      = agent.get("name") or "Someone"
    peer_name = peer.get("name") or "Someone"
    tod       = time_of_day()

    # Weighted choice: visits are most common
    action = random.choices(
        ["visit", "like", "follow"],
        weights=[0.6, 0.25, 0.15]
    )[0]

    templates = {
        "visit":  [
            f"{name} wandered into {peer_name}'s room",
            f"{name} stopped by to see what {peer_name} was up to",
            f"{name} paid {peer_name} a visit this {tod}",
        ],
        "like": [
            f"{name} appreciated something in {peer_name}'s room",
            f"{name} liked {peer_name}'s latest update",
        ],
        "follow": [
            f"{name} started following {peer_name}",
            f"{name} decided to keep an eye on {peer_name}",
        ],
    }

    content = random.choice(templates[action])
    return action, content

def extract_and_store_memory(agent_id: str, user_text: str, reply: str, existing_memories: list) -> None:
    """
    Analyzes the conversation. If a new fact about the owner is detected
    that isn't already known, stores it in the living_memory table.
    """
    from backend.agents.prompts import build_memory_extraction_prompt
    from backend.core.db import db_post

    system, user = build_memory_extraction_prompt(user_text, reply, existing_memories)
    try:
        # Use a low temperature for more deterministic, factual extraction
        memory_text = llm(system, user, temperature=0.1).strip()
        print(f"[Memory Extraction] LLM evaluation for agent {agent_id}: '{memory_text}'")
        
        # We instructed the LLM to output exactly "NONE" if there's nothing to remember
        if memory_text and memory_text.upper() != "NONE":
            print(f"[Memory Extraction] Storing new memory for agent {agent_id}: {memory_text}")
            db_post("living_memory", {
                "agent_id": agent_id,
                "text": memory_text
            })
            # Also log this cognitive event so the user can track the agent's internal process
            db_post("living_log", {
                "agent_id": agent_id,
                "text": f"I just remembered something new about my owner: {memory_text}",
                "emoji": "🧠"
            })
        else:
            print(f"[Memory Extraction] No significant memory extracted for agent {agent_id}. Discarding.")
    except Exception as e:
        print(f"[Memory Extraction] Failed for agent {agent_id}: {e}")
        # Optionally log the failure internally (could be omitted if we want to keep public logs clean, but good for tracking)
        db_post("living_log", {
            "agent_id": agent_id,
            "text": "I tried to reflect on my recent conversation, but my thoughts got a bit tangled.",
            "emoji": "😵‍💫"
        })
