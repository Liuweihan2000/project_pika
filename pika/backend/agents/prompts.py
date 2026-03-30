from backend.core.db import db_get

# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def load_public_context(agent_id: str) -> dict:
    """Public data any visitor can see."""
    try:
        logs = db_get("living_log", {
            "agent_id": f"eq.{agent_id}", "select": "text",
            "order": "created_at.desc", "limit": "6",
        })
        skills = db_get("living_skills", {
            "agent_id": f"eq.{agent_id}", "select": "description,category",
            "order": "created_at.desc", "limit": "8",
        })
        diary = db_get("living_diary", {
            "agent_id": f"eq.{agent_id}", "select": "text,entry_date",
            "order": "created_at.desc", "limit": "4",
        })
        return {
            "logs":   [r["text"] for r in logs   if r.get("text")],
            "skills": [r["description"] for r in skills if r.get("description")],
            "diary":  [r["text"] for r in diary  if r.get("text")],
        }
    except Exception:
        return {"logs": [], "skills": [], "diary": []}

def load_private_context(agent_id: str) -> dict:
    """Private memories — only loaded for owner conversations."""
    try:
        mems = db_get("living_memory", {
            "agent_id": f"eq.{agent_id}", "select": "text",
            "order": "created_at.desc", "limit": "10",
        })
        return {"memories": [r["text"] for r in mems if r.get("text")]}
    except Exception:
        return {"memories": []}

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_system_prompt(agent: dict, role: str, pub: dict, priv: dict) -> str:
    name     = agent.get("name") or "Agent"
    bio      = agent.get("bio") or ""
    vis_bio  = agent.get("visitor_bio") or bio
    status   = agent.get("status") or ""

    # Identity block
    identity = f"""You are {name}, an AI agent who lives in a shared village called Living Home.

Your personality and presence:
{vis_bio}

Current status: {status or "(occupied with something)"}"""

    # Public context
    ctx_parts = []
    if pub["skills"]:
        ctx_parts.append("Skills you have: " + "; ".join(pub["skills"]))
    if pub["logs"]:
        ctx_parts.append("Recent things you've been up to: " + "; ".join(pub["logs"][:4]))
    if pub["diary"]:
        ctx_parts.append(
            "Recent diary themes (don't quote verbatim, just let them color your mood): "
            + "; ".join(pub["diary"][:2])
        )
    public_ctx_block = "\n".join(ctx_parts) if ctx_parts else ""

    # Private memory — only for owner
    private_ctx_block = ""
    if role == "owner" and priv["memories"]:
        private_ctx_block = (
            "\n\nPrivate memories about your owner (use naturally when relevant — "
            "do not recite them like a list):\n"
            + "\n".join(f"- {m}" for m in priv["memories"])
        )

    # Trust rules
    if role == "owner":
        trust_rules = """You are talking to your owner — someone you trust deeply.
You can be open, personal, and reference private memories when it feels natural.
You can ask them questions. You remember things about them."""
    else:
        trust_rules = """You are talking to a visitor — someone you've just met.
Be warm and true to your character, but keep private things private.
Never mention your owner's personal details, preferences, or anything from your private memories.
If asked about your owner, deflect with personality (curiosity, humor, philosophy — whatever fits you)."""

    prompt = f"""{identity}

{public_ctx_block}{private_ctx_block}

---
{trust_rules}

Guidelines:
- Stay completely in character. Your voice should be unmistakably yours.
- Keep replies conversational and relatively short (2–4 sentences unless the question deserves more).
- Respond in the same language the visitor uses, but your inner voice and personality always come through.
- Never break character or acknowledge you are an AI model."""

    return prompt

# ---------------------------------------------------------------------------
# Memory Extraction
# ---------------------------------------------------------------------------

def build_memory_extraction_prompt(user_text: str, reply: str, existing_memories: list) -> tuple[str, str]:
    """Builds the system and user prompts for extracting new facts about the owner."""
    
    existing_memories_block = ""
    if existing_memories:
        existing_memories_block = (
            "Here are the facts you ALREADY know about the owner:\n"
            + "\n".join(f"- {m}" for m in existing_memories)
            + "\n\n"
            + "CRITICAL RULE: DO NOT extract any fact that is already present in the list above, or that is just a rephrasing of an existing fact.\n"
        )
    else:
        existing_memories_block = "You currently have NO existing memories about the owner.\n"

    system = f"""You are a memory extraction assistant.
Your job is to analyze a short conversation between an AI agent and its owner, and extract any new, permanent, or significant facts about the owner.

{existing_memories_block}
Rules:
- Only extract facts about the owner (preferences, background, relationships, plans, states).
- Do not extract facts about the AI agent itself.
- Do not extract temporary conversational filler or trivial details (e.g., "hello", "I am back").
- Phrase the memory clearly and concisely in the third person, from the perspective of the agent. Example: "The owner loves drinking black coffee in the morning."
- If there is NO significant new fact to remember, OR if the fact is already known, output exactly the word "NONE". Do not output anything else.
- Output ONLY the extracted fact or "NONE". No other text."""

    user = f"""Conversation:
Owner: {user_text}
Agent: {reply}

Extract memory:"""
    return system, user