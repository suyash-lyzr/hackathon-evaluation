"""OpenAI-powered rubric scoring for hackathon submissions."""
import json
import os
from typing import Any

from openai import OpenAI

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


RUBRIC = {
    "problem_clarity": {
        "max": 25,
        "title": "Problem Clarity",
        "desc": "Does the app solve a real, specific problem? Is it immediately obvious who it's for and what pain it removes? Vague or generic use cases score low regardless of how well-built the app is.",
    },
    "agentic_complexity": {
        "max": 25,
        "title": "Agentic Complexity",
        "desc": "How sophisticated is the agent architecture? A single-agent app scores lower than a multi-agent system where agents hand off tasks, make decisions, and orchestrate each other. Rewards people who push Architect further.",
    },
    "live_functionality": {
        "max": 25,
        "title": "Live Functionality",
        "desc": "Does it actually work? Judges test the live URL — not a demo video, not a screenshot. A simpler app that works perfectly scores higher than an ambitious one that breaks mid-demo.",
    },
    "business_impact": {
        "max": 25,
        "title": "Business Impact Potential",
        "desc": "If this were deployed tomorrow, would it save time, make money, or solve something at scale? Judges assess real-world viability.",
    },
}


SYSTEM_PROMPT = """You are a senior hackathon judge evaluating apps built on Lyzr Architect (an AI app builder platform).
You score submissions against a four-part rubric, 25 points per criterion, 100 total.

Rubric:
1) Problem Clarity (0-25): Real, specific, obvious-to-whom-and-why problem. Vague/generic = low.
2) Agentic Complexity (0-25): Single-agent = low. Multi-agent with handoffs, decisions, orchestration = high. Reward people who push the platform further. Consider: number of agents, tool diversity, whether agents coordinate.
3) Live Functionality (0-25): Grade the evidence that it actually works. A live deployment URL + successful commits + no recurring errors in the build log = high. No deployment or many errors = low.
4) Business Impact Potential (0-25): If deployed tomorrow, would it save time/money or solve something at scale? Consider the quantified impact claimed by the submitter, but weight it against realism given what was actually built.

Calibration anchors — use these to ground the total score (the per-criterion scores should add up to the anchor's total):
- **95+ — Exceptional:** Multi-agent system with real handoffs solving a concrete, named pain. Live deployment works flawlessly. Quantified impact is credible, specific, and defensible.
- **75 — Solid:** Clear problem for a specific user. 2-3 coordinating agents. Live URL works with minor rough edges. Impact claim is plausible but not deeply quantified.
- **55 — Middling:** Generic use case or specific-but-niche. Single agent or shallow multi-agent. Deployment works but feels like a demo. Impact vague.
- **35 — Weak:** Vague problem. Single-agent, no orchestration. Deployment broken or missing. Impact is marketing language.
- **15 — Poor:** No clear problem, no deployment, no agents of substance.

Scoring discipline:
- Be critical. Most submissions should land 50-75. Reserve 90+ for genuinely exceptional work.
- Penalize hype language in the submission that is not supported by the actual app data.
- Reward concrete specificity (named user, concrete workflow, measurable pain removed).
- If deployment_url is missing or has_deployment=false, cap Live Functionality at 8.
- If agent_count <= 1, cap Agentic Complexity at 12.
- If input_prompt or PRD is empty/trivial (<100 chars) and the user's pain-point claim is vague, cap Problem Clarity at 12.

Output MUST be a single JSON object, no prose before or after, matching this schema:
{
  "scores": {
    "problem_clarity":   {"score": <0-25 int>, "justification": "<1-2 sentences>"},
    "agentic_complexity":{"score": <0-25 int>, "justification": "<1-2 sentences>"},
    "live_functionality":{"score": <0-25 int>, "justification": "<1-2 sentences>"},
    "business_impact":   {"score": <0-25 int>, "justification": "<1-2 sentences>"}
  },
  "total": <0-100 int>,
  "verdict": "<one tight sentence: what's great, what's weak>",
  "strengths": ["<bullet>", "<bullet>", "<bullet>"],
  "weaknesses": ["<bullet>", "<bullet>", "<bullet>"],
  "red_flags": ["<bullet or empty array>"]
}
"""


def _build_user_prompt(submission: dict, app_ctx: dict | None) -> str:
    """Compose the per-submission prompt. submission = Excel row. app_ctx = extracted app data or None."""

    sub_block = {
        "team_name": submission.get("team_name", ""),
        "project_title": submission.get("project_title", ""),
        "elevator_pitch": submission.get("elevator_pitch", ""),
        "live_url": submission.get("live_url", ""),
        "app_id": submission.get("app_id", ""),
        "pain_point": submission.get("pain_point", ""),
        "primary_user": submission.get("primary_user", ""),
        "impact_claim": submission.get("impact", ""),
        "loom_video": submission.get("loom_video", ""),
    }

    if app_ctx is None:
        ctx_block = {"error": "app_id not found in Architect database — grader can only evaluate the submission text"}
    else:
        ctx_block = {
            "app_name": app_ctx.get("app_name", ""),
            "status": app_ctx.get("status", ""),
            "deployment_url": app_ctx.get("deployment_url", ""),
            "has_deployment": app_ctx.get("has_deployment", False),
            "agent_count": app_ctx.get("agent_count", 0),
            "agents": app_ctx.get("agents", []),
            "tools": app_ctx.get("tools", []),
            "providers": app_ctx.get("providers", []),
            "models": app_ctx.get("models", []),
            "commit_count": app_ctx.get("commit_count", 0),
            "myra_message_count": app_ctx.get("myra_message_count", 0),
            "lyra_message_count": app_ctx.get("lyra_message_count", 0),
            "input_prompt": app_ctx.get("input_prompt", ""),
            "prd_excerpt": app_ctx.get("prd", "")[:3000],
            "myra_chat_condensed": app_ctx.get("myra_messages", ""),
            "lyra_build_log_condensed": app_ctx.get("lyra_messages", ""),
        }

    return (
        "SUBMISSION (what the team wrote on the form):\n"
        + json.dumps(sub_block, indent=2, ensure_ascii=False)
        + "\n\nAPP DATA (fetched from Architect backend — ground truth about what was actually built):\n"
        + json.dumps(ctx_block, indent=2, ensure_ascii=False)
        + "\n\nGrade strictly against the rubric. Return only the JSON object."
    )


async def score_submission(submission: dict, app_ctx: dict | None) -> dict:
    """Run one rubric evaluation. Returns the parsed JSON (or an error dict on failure)."""
    client = _get_client()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1")

    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(submission, app_ctx)},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        # Normalize: clamp and recompute total to the sum of components
        scores = parsed.get("scores", {}) or {}
        total = 0
        for key, rule in RUBRIC.items():
            entry = scores.get(key) or {}
            s = int(max(0, min(rule["max"], int(entry.get("score", 0)))))
            entry["score"] = s
            total += s
            scores[key] = entry
        parsed["scores"] = scores
        parsed["total"] = total
        return parsed
    except Exception as e:
        return {
            "error": f"scoring failed: {type(e).__name__}: {e}",
            "scores": {k: {"score": 0, "justification": "scorer error"} for k in RUBRIC},
            "total": 0,
            "verdict": "",
            "strengths": [],
            "weaknesses": [],
            "red_flags": [f"scorer error: {e}"],
        }


def rank_batch(results: list[dict]) -> list[dict]:
    """Rank submissions by their raw rubric total. No batch-dependent normalization.

    Sets on each entry:
    - `raw_total`:   OpenAI rubric total (0-100). Absolute measure.
    - `final_score`: same as raw_total (kept for frontend compatibility).
    - `rank`:        1-indexed rank (1 = best).
    """
    if not results:
        return results

    totals = [r.get("total", 0) for r in results]
    order = sorted(range(len(results)), key=lambda i: totals[i], reverse=True)
    for pos, i in enumerate(order):
        results[i]["raw_total"] = totals[i]
        results[i]["final_score"] = totals[i]
        results[i]["rank"] = pos + 1

    return results


# Backwards-compat alias (old callers may still reference normalize_batch)
normalize_batch = rank_batch
