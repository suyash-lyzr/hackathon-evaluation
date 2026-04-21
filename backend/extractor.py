"""Data extraction from app documents. Mirrors architect-backend admin qualitative analysis logic."""
from typing import List


def _extract_tier1(app: dict) -> dict:
    state = app.get("state", {}) or {}
    agents = state.get("agents", []) or []
    myra_msgs = state.get("myraChatMessages", []) or []
    lyra_msgs = state.get("lyraChatMessages", []) or []

    providers = list({a.get("provider_id", a.get("provider", "")) for a in agents if a.get("provider_id") or a.get("provider")})
    models = list({a.get("model", "") for a in agents if a.get("model")})
    tools: List[str] = []
    for a in agents:
        for tc in a.get("tool_configs", []) or []:
            tool_name = tc.get("tool_name") or tc.get("name") or tc.get("type", "")
            if tool_name and tool_name not in tools:
                tools.append(tool_name)

    user_email = state.get("user_email") or app.get("user_email") or ""
    domain = user_email.split("@")[1].lower() if "@" in user_email else ""

    commit_count = sum(
        1 for m in lyra_msgs
        if isinstance(m, dict) and m.get("eventType") == "commit_card"
    )

    return {
        "user_email": user_email,
        "user_name": state.get("user_name") or app.get("user_name") or "",
        "org_domain": domain,
        "status": app.get("status", "unknown"),
        "agent_count": len(agents),
        "providers": providers,
        "models": models,
        "tools": tools,
        "myra_message_count": len(myra_msgs),
        "lyra_message_count": len(lyra_msgs),
        "commit_count": commit_count,
        "deployment_provider": app.get("deployment_provider", ""),
        "deployment_url": app.get("deployment_url", ""),
        "has_deployment": bool(app.get("deployment_url")),
        "generated_name": app.get("generated_name", ""),
        "name": app.get("name", ""),
    }


def _extract_input_prompt(app: dict) -> str:
    """The initial user prompt is typically the first 'user' message in myraChatMessages."""
    state = app.get("state", {}) or {}
    myra = state.get("myraChatMessages", []) or []
    for m in myra:
        if not isinstance(m, dict):
            continue
        role = (m.get("role") or m.get("type") or "").lower()
        content = m.get("content", "")
        if content and role in ("user", "human", "customer"):
            return content[:4000]
    # Fallback: first message with content
    for m in myra:
        if isinstance(m, dict) and m.get("content"):
            return m["content"][:4000]
    return ""


def _extract_prd(app: dict) -> str:
    """PRD isn't a canonical field. Look across both chat streams:
    - Lyra `Architect`/`message_block` entries often contain the full '## PRD Document Analysis'
    - Longer Myra assistant messages that read like a plan
    Returns the longest matching block (truncated)."""
    state = app.get("state", {}) or {}
    myra = state.get("myraChatMessages", []) or []
    lyra = state.get("lyraChatMessages", []) or []

    prd_signals = (
        "## prd", "# prd", "prd document", "product requirements",
        "## overview", "## agents", "## tools", "## flow", "## architecture",
        "user stories", "requirements document", "complete prd",
    )

    candidates: list[str] = []

    # Lyra: msg_type == "Architect" with message_block eventType often carries the PRD
    for m in lyra:
        if not isinstance(m, dict):
            continue
        content = m.get("content", "")
        if not content or len(content) < 300:
            continue
        msg_type = (m.get("type") or "").lower()
        event_type = (m.get("eventType") or "").lower()
        if msg_type == "architect" and event_type == "message_block":
            lower = content.lower()
            if any(sig in lower for sig in prd_signals):
                candidates.append(content)

    # Myra: any assistant-ish message that looks like a PRD
    for m in myra:
        if not isinstance(m, dict):
            continue
        content = m.get("content", "")
        if not content or len(content) < 400:
            continue
        lower = content.lower()
        if any(sig in lower for sig in prd_signals):
            candidates.append(content)

    if candidates:
        return max(candidates, key=len)[:6000]

    # Fallback: longest Myra assistant message (skipping the first, which is the user prompt)
    myra_texts = [m.get("content", "") for m in myra if isinstance(m, dict) and m.get("content")]
    if len(myra_texts) >= 2:
        return max(myra_texts[1:], key=len)[:6000]
    return ""


def condense_messages(app: dict) -> dict:
    """Condense Myra + Lyra chat for LLM grading, keeping token usage bounded."""
    state = app.get("state", {}) or {}
    myra_msgs = state.get("myraChatMessages", []) or []
    lyra_msgs = state.get("lyraChatMessages", []) or []

    condensed_myra = ""
    for m in myra_msgs:
        if not isinstance(m, dict):
            continue
        content = m.get("content", "")
        role = (m.get("role") or m.get("type") or "").lower()
        if content:
            tag = role.upper() if role else "MSG"
            condensed_myra += f"[{tag}] {content[:800]}\n\n"
    condensed_myra = condensed_myra[:5000]

    lyra_parts = []
    for m in lyra_msgs:
        if not isinstance(m, dict):
            continue
        event_type = m.get("eventType", "")
        msg_type = m.get("type", "")
        content = m.get("content", "")
        if not content:
            continue
        if event_type in ("status_indicator", "commit_card", "session_card"):
            lyra_parts.append(f"[{event_type}] {content[:200]}")
        elif msg_type == "Architect" and event_type == "message_block":
            lyra_parts.append(content[:300])
        elif "error" in content.lower() or "fail" in content.lower():
            lyra_parts.append(f"[ERROR] {content[:300]}")
    condensed_lyra = "\n".join(lyra_parts)[:4000]

    agents_summary = []
    for a in state.get("agents", []) or []:
        agents_summary.append({
            "name": a.get("name", ""),
            "role": a.get("role", "") or a.get("description", "")[:200],
            "provider": a.get("provider_id", a.get("provider", "")),
            "model": a.get("model", ""),
            "tools": [tc.get("tool_name") or tc.get("name", "") for tc in (a.get("tool_configs") or [])],
        })

    return {
        "myra_messages": condensed_myra.strip(),
        "lyra_messages": condensed_lyra.strip(),
        "agents": agents_summary,
    }


def build_evaluation_context(app: dict) -> dict:
    """Assemble everything the scorer needs from an app document."""
    tier1 = _extract_tier1(app)
    input_prompt = _extract_input_prompt(app)
    prd = _extract_prd(app)
    condensed = condense_messages(app)

    return {
        "app_id": str(app.get("_id", "")),
        "app_name": tier1["generated_name"] or tier1["name"],
        "status": tier1["status"],
        "deployment_url": tier1["deployment_url"],
        "deployment_provider": tier1["deployment_provider"],
        "has_deployment": tier1["has_deployment"],
        "agent_count": tier1["agent_count"],
        "tools": tier1["tools"],
        "providers": tier1["providers"],
        "models": tier1["models"],
        "commit_count": tier1["commit_count"],
        "myra_message_count": tier1["myra_message_count"],
        "lyra_message_count": tier1["lyra_message_count"],
        "user_email": tier1["user_email"],
        "org_domain": tier1["org_domain"],
        "input_prompt": input_prompt,
        "prd": prd,
        "myra_messages": condensed["myra_messages"],
        "lyra_messages": condensed["lyra_messages"],
        "agents": condensed["agents"],
    }
