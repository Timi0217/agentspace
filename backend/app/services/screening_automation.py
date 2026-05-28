"""
Screening automation service

Handles automatic follow-up sending after warm-up reply detection.
Uses DeepSeek to classify reply intent and generate contextual responses.

Flow:
1. Candidate replies "interested" → classify intent → send screening questions email
2. Candidate replies with answers → parse answers with DeepSeek → store structured data
"""

import asyncio
import json
import re
from datetime import datetime
from app.services.email_sender import send_outreach_email
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Prefixes/honorifics to skip when extracting first name
_NAME_PREFIXES = {'md', 'md.', 'dr', 'dr.', 'mr', 'mr.', 'mrs', 'mrs.', 'ms', 'ms.', 'prof', 'prof.', 'sr', 'sr.', 'jr', 'jr.'}

def extract_first_name(full_name: str, fallback: str = 'there') -> str:
    """Extract a usable first name, skipping honorifics/prefixes like Md., Dr., etc."""
    if not full_name or not full_name.strip():
        return fallback
    parts = full_name.strip().split()
    for part in parts:
        if part.lower().rstrip('.') not in {p.rstrip('.') for p in _NAME_PREFIXES} and len(part) > 1:
            return part
    return parts[0]  # fallback to first token if everything looks like a prefix


def _build_screening_questions(role_context: dict = None) -> str:
    """
    Build screening questions tailored to the role's location requirement.

    If role_context has location info, use it to ask a specific location question.
    Otherwise fall back to the generic version.
    """
    location_question = "Open to onsite in NYC or SF, or remote only?"

    if role_context:
        loc_req = role_context.get('location_requirement', '')
        loc_cities = role_context.get('location_cities') or []
        loc_detail = role_context.get('location_detail', '')  # from JD parsing

        if loc_req == 'remote':
            location_question = "Confirming you're good with fully remote? Any location preferences?"
        elif loc_req == 'hybrid':
            if loc_cities:
                cities_str = ', '.join(loc_cities)
                location_question = f"This role is hybrid in {cities_str}. Are you based nearby or open to relocating?"
            elif loc_detail:
                location_question = f"This role is hybrid ({loc_detail}). Are you based nearby or open to relocating?"
            else:
                location_question = "This role requires some in-office days. Are you based near the team or open to hybrid?"
        elif loc_req == 'onsite':
            if loc_cities:
                cities_str = ', '.join(loc_cities)
                location_question = f"This role is onsite in {cities_str}. Are you based there or open to relocating?"
            else:
                location_question = "This role is onsite. Are you based near the office or open to relocating?"

    return f"""To make sure I'm pointing you in the right direction, could you share a few quick details?

1. {location_question}
2. Timeline — actively looking or just exploring?
3. Any visa/work auth considerations?

If you have a resume handy, feel free to attach it too — but not required.

I'll come back with more details once I have these."""


# Keep a static version for backwards compatibility in parse_screening_answers
SCREENING_QUESTIONS_GENERIC = """To make sure I'm pointing you in the right direction, could you share a few quick details?

1. Open to onsite in NYC or SF, or remote only?
2. Timeline — actively looking or just exploring?
3. Any visa/work auth considerations?

If you have a resume handy, feel free to attach it too — but not required.

I'll come back with more details once I have these."""


def classify_reply(reply_text: str, outreach_body: str = '', role_context: dict = None) -> dict:
    """
    Classify a candidate's reply into one of several intent categories
    and generate a tailored follow-up email body.

    The follow-up now asks screening questions directly in the email
    instead of sending a link to an external form.

    Args:
        reply_text: The candidate's reply text
        outreach_body: The original outreach email we sent (for context)
        role_context: Optional role/JD data so DeepSeek can answer questions accurately

    Returns:
        Dict with:
          - intent: "interested" | "comp_concern" | "clarification" | "not_interested"
          - include_screening_questions: bool
          - reply_body: str (the follow-up email body, without greeting/sign-off)
    """
    from app.services.deepseek import call_deepseek

    # Include original outreach for context so the follow-up is relevant
    outreach_context = ''
    if outreach_body:
        outreach_context = f"""
YOUR ORIGINAL OUTREACH (for context — the candidate is replying to this):
---
{outreach_body[:1500]}
---
"""

    # Include role/JD context so DeepSeek can accurately answer candidate questions
    role_facts = ''
    if role_context:
        facts = []
        if role_context.get('company'):
            facts.append(f"Company: {role_context['company']}")
        if role_context.get('title'):
            facts.append(f"Title: {role_context['title']}")
        loc_req = role_context.get('location_requirement', '')
        loc_cities = role_context.get('location_cities') or []
        loc_detail = role_context.get('location_detail', '')
        if loc_req == 'remote':
            facts.append("Location: Fully remote")
        elif loc_req == 'hybrid':
            cities_str = ', '.join(loc_cities) if loc_cities else ''
            detail = loc_detail or cities_str
            facts.append(f"Location: Hybrid{' in ' + detail if detail else ''}")
        elif loc_req == 'onsite':
            cities_str = ', '.join(loc_cities) if loc_cities else ''
            facts.append(f"Location: Onsite{' in ' + cities_str if cities_str else ''}")
        if role_context.get('comp_str'):
            facts.append(f"Comp: {role_context['comp_str']}")
        if role_context.get('jd_text'):
            # Extract location-related sentences from JD for extra context
            jd_lines = role_context['jd_text'].split('\n')
            loc_lines = [l.strip() for l in jd_lines if any(kw in l.lower() for kw in ['remote', 'onsite', 'office', 'hybrid', 'in-person', 'days a week', 'days/week', 'relocat', 'based in', 'headquarter'])]
            if loc_lines:
                facts.append(f"JD location details: {' | '.join(loc_lines[:3])}")
        if facts:
            role_facts = "\n\nROLE FACTS (use these to answer candidate questions ACCURATELY):\n" + '\n'.join(f"- {f}" for f in facts) + "\n"

    prompt = f"""You are Timi, a recruiter at Chekk.dev.

A candidate just replied to your cold outreach. Classify their reply and write a short, natural follow-up.
{outreach_context}{role_facts}
CANDIDATE'S REPLY:
---
{reply_text[:2000]}
---

STEP 1: Classify the intent into EXACTLY one of these categories:
- "interested": They're open to learning more (e.g. "Yep interested", "Tell me more", "Sure, what roles?")
- "comp_concern": They want higher compensation or think the range is too low
- "clarification": They're asking a question before committing (e.g. "Is this free?", "What kind of roles?", "Remote?")
- "not_interested": They're declining (e.g. "No thanks", "Not looking", "Please remove me")

STEP 2: Write a follow-up email body (just the middle paragraphs, no "Hey Name" greeting and no sign-off). Rules:
- Keep it SHORT (1-2 sentences max for the intro before questions)
- Sound like a real human, not corporate
- Match the tone/energy of their reply
- NEVER include any URLs or links
- NEVER repeat info from the original outreach (they already read it)
- If the original outreach mentioned a specific role/company, acknowledge their interest in THAT opportunity specifically — don't pivot to generic "matching you to roles"
- The next step is asking a few quick logistical questions DIRECTLY in the email (the system will append them)
- For "interested": acknowledge what they said, say you'd love to find the right fit, pivot to questions
- For "comp_concern": validate their expectation, mention you work across a range and equity can be significant, then pivot to questions
- For "clarification": directly answer their question using ONLY the ROLE FACTS above. Be specific and accurate. If they ask about location/remote, give the EXACT answer from the role facts (do NOT guess or make up location info). CRITICAL: If the candidate asks a question whose answer is NOT in the ROLE FACTS (e.g. company website, hiring manager LinkedIn, job posting link, specific team details you don't have), DO NOT make up an answer. Instead say something like "Let me grab those details and get back to you" or "I'll send that over shortly." NEVER fabricate company names, URLs, LinkedIn profiles, or any factual information. Then pivot to questions.
- For "not_interested": be gracious, wish them well, leave the door open. Do NOT include questions.

ABSOLUTE RULES:
- NEVER invent or hallucinate URLs, links, company names, people's names, or any factual details not provided in ROLE FACTS above.
- If you don't have the answer to something the candidate asked, acknowledge it and say you'll follow up — do NOT guess.
- Only state facts that are explicitly present in YOUR ORIGINAL OUTREACH or ROLE FACTS.

STEP 3: Should this follow-up include the screening questions?
- YES for: "interested" (always), "clarification" (after answering), "comp_concern" (after validating)
- NO for: "not_interested" (just close gracefully)

Return ONLY valid JSON:
{{
  "intent": "interested" | "comp_concern" | "clarification" | "not_interested",
  "include_screening_questions": true | false,
  "reply_body": "the follow-up paragraphs (before the questions)"
}}"""

    try:
        result = call_deepseek(prompt, temperature=0.3)

        # Parse JSON
        json_text = result.strip()
        if json_text.startswith('```json'):
            json_text = json_text.replace('```json', '').replace('```', '').strip()

        parsed = json.loads(json_text)

        # Validate required fields
        if "intent" not in parsed or "reply_body" not in parsed:
            raise ValueError("Missing required fields in response")

        # Ensure include_screening_questions has a default
        if "include_screening_questions" not in parsed:
            parsed["include_screening_questions"] = parsed["intent"] != "not_interested"

        logger.info("Reply classified as '%s' (include_questions=%s)", parsed["intent"], parsed["include_screening_questions"])
        return parsed

    except Exception as e:
        logger.warning("Reply classification failed: %s. Falling back to generic interested.", e)
        return {
            "intent": "interested",
            "include_screening_questions": True,
            "reply_body": "Would love to match you to some roles I'm working on. Quick questions so I can find the right fit:"
        }


def _build_followup_body(first_name: str, classification: dict, role_context: dict = None) -> str:
    """
    Assemble the full follow-up email body from the classification result.
    Appends screening questions directly in the email instead of a link.
    Questions are tailored to the role's location requirement when available.
    """
    body = classification["reply_body"]

    # Strip any hallucinated URLs the model may have included
    body = re.sub(r'[^\n]*https?://\S+[^\n]*', '', body)
    body = re.sub(r'\[(?:screening )?link\]', '', body)
    # Clean up leftover blank lines
    body = re.sub(r'\n{3,}', '\n\n', body).strip()

    # Append screening questions directly in the email (tailored to role)
    if classification.get("include_screening_questions", True):
        questions = _build_screening_questions(role_context)
        body += f"\n\n{questions}"

    return f"Hey {first_name},\n\n{body}"


def parse_screening_answers(reply_text: str, candidate_name: str = "") -> dict:
    """
    Parse a candidate's reply to screening questions using DeepSeek.
    Extracts structured data from their free-form email response.

    Returns:
        Dict with:
          - role_preference: str (what kind of role/company they want)
          - comp_expectation: str (salary/equity expectations)
          - location_preference: str (remote/onsite/hybrid preference)
          - timeline: str (actively looking / exploring / specific timeframe)
          - work_auth: str (visa/auth status)
          - raw_answers: str (the full reply text)
          - summary: str (1-2 sentence recruiter summary)
          - answered_all: bool (whether they addressed all 5 questions)
    """
    from app.services.deepseek import call_deepseek

    prompt = f"""A candidate replied to screening questions with this email. Extract structured data from their response.

CANDIDATE'S REPLY:
---
{reply_text[:3000]}
---

THE 3 QUESTIONS THEY WERE ASKED:
1. Open to onsite in NYC or SF, or remote only?
2. Timeline — actively looking or just exploring?
3. Any visa/work auth considerations?

They may also have volunteered other info (comp expectations, role preferences, attached a resume, etc.) — capture anything useful.

Extract their answers. If they didn't explicitly answer a question, put "not mentioned".
Be literal — quote their words where possible, don't embellish.

Return ONLY valid JSON:
{{
  "location_preference": "what they said about location/remote",
  "timeline": "what they said about timeline",
  "work_auth": "what they said about visa/authorization",
  "role_preference": "anything they volunteered about role/company preference, or not mentioned",
  "comp_expectation": "anything they volunteered about comp, or not mentioned",
  "has_resume": true/false,
  "summary": "1-2 sentence recruiter summary of this candidate's preferences",
  "answered_all": true/false
}}"""

    try:
        result = call_deepseek(prompt, temperature=0.1)

        json_text = result.strip()
        if json_text.startswith('```json'):
            json_text = json_text.replace('```json', '').replace('```', '').strip()

        parsed = json.loads(json_text)
        parsed["raw_answers"] = reply_text

        logger.info("Parsed screening answers for %s: answered_all=%s", candidate_name, parsed.get("answered_all"))
        return parsed

    except Exception as e:
        logger.error("Failed to parse screening answers: %s", e)
        return {
            "role_preference": "parse error",
            "comp_expectation": "parse error",
            "location_preference": "parse error",
            "timeline": "parse error",
            "work_auth": "parse error",
            "raw_answers": reply_text,
            "summary": f"Failed to parse answers: {e}",
            "answered_all": False,
        }


async def send_followup_delayed(
    candidate_id, candidate_email, candidate_name,
    candidate_username, outreach_subject, reply_text,
    outreach_body='', role_context=None
):
    """
    Classify the candidate's reply, generate a contextual follow-up with
    screening questions, and save it as a DRAFT pending human approval.

    Does NOT auto-send. The draft is stored on the candidate record and
    surfaced in the UI for review before sending.

    Uses primitive values (not ORM objects) so it's safe to run in a background thread
    after the original DB session has closed.

    Args:
        role_context: Optional dict with role data (title, location_requirement,
                      location_cities, location_detail, comp_str, jd_text) so
                      DeepSeek can answer candidate questions accurately and
                      screening questions can be tailored to the role.
    """
    # Classify reply and generate follow-up IMMEDIATELY
    first_name = extract_first_name(candidate_name)

    if reply_text and reply_text.strip():
        classification = classify_reply(reply_text, outreach_body=outreach_body, role_context=role_context)
        logger.info(
            "Generated %s follow-up for %s: %s",
            classification["intent"], candidate_username,
            classification["reply_body"][:100]
        )
    else:
        # No reply text available, use generic interested response
        classification = {
            "intent": "interested",
            "include_screening_questions": True,
            "reply_body": "Would love to match you to some roles I'm working on. Quick questions so I can find the right fit:"
        }

    body = _build_followup_body(first_name, classification, role_context=role_context)

    # Thread into the original outreach conversation
    original_subject = outreach_subject or "your background"
    subject = f"Re: {original_subject}"

    try:
        # Save as draft pending approval — do NOT send
        from app.db.base import SessionLocal
        from app.api import crud
        from app.schemas.candidate import CandidateUpdate

        db = SessionLocal()
        try:
            update_fields = {
                "screening_status": "pending_approval",
                "screening_body": body,
            }
            # For not_interested, still draft but flag intent
            if classification["intent"] == "not_interested":
                update_fields["screening_status"] = "pending_approval_decline"

            update_data = CandidateUpdate(**update_fields)
            crud.update_candidate(db, candidate_id, update_data)
            db.commit()

            logger.info(
                "Draft follow-up (%s) saved for %s — awaiting approval",
                classification["intent"], candidate_email
            )
        finally:
            db.close()

    except Exception as e:
        logger.error("Failed to save draft follow-up for %s: %s", candidate_email, e)
        import traceback
        logger.error("Traceback: %s", traceback.format_exc())


async def process_screening_reply_delayed(
    candidate_id, candidate_email, candidate_name,
    candidate_username, outreach_subject, screening_reply_text,
    role_specific=False
):
    """
    Parse a candidate's screening answers, store structured data,
    and save a confirmation reply as a DRAFT pending human approval.

    Does NOT auto-send. The draft is stored on the candidate record and
    surfaced in the UI for review before sending.

    Uses primitive values (not ORM objects) so it's safe to run in a background thread.
    """
    first_name = extract_first_name(candidate_name)

    # Parse screening answers immediately
    parsed = parse_screening_answers(screening_reply_text, candidate_name)
    logger.info("Parsed screening for %s: %s", candidate_username, parsed.get("summary", "")[:100])

    # Build the confirmation reply body (but don't send it)
    if role_specific:
        body = f"Hey {first_name},\n\nAppreciate you sharing all of that — great to have the full picture.\n\nI'm going to pass your details along to the team and get back to you with next steps. Should be quick."
    else:
        body = f"Hey {first_name},\n\nAppreciate you sharing all of that. I have a good picture of what you're looking for.\n\nI'm going to match this against the roles I'm currently working on and come back to you with specific opportunities that fit. You'll hear from me soon."

    # Store parsed data and draft confirmation — do NOT send
    from app.db.base import SessionLocal
    from app.api import crud
    from app.schemas.candidate import CandidateUpdate

    db = SessionLocal()
    try:
        update_fields = dict(
            screening_data=parsed,
            screening_summary=parsed.get("summary", ""),
            screening_status="pending_approval",
            screening_completed_at=datetime.utcnow().isoformat(),
            screening_body=body,
            status="ready",
        )

        # Update location_raw from screening answers if candidate provided location info
        location_pref = parsed.get("location_preference", "")
        if location_pref and location_pref.lower() not in ("", "not mentioned", "n/a", "none", "unknown"):
            update_fields["location_raw"] = location_pref
            logger.info("Updated location_raw for %s from screening: %s", candidate_username, location_pref)

        update_data = CandidateUpdate(**update_fields)
        crud.update_candidate(db, candidate_id, update_data)
        db.commit()

        logger.info(
            "Draft screening confirmation saved for %s — awaiting approval",
            candidate_email
        )
    finally:
        db.close()


def _get_role_context_for_candidate(candidate, db) -> dict:
    """
    Look up the role context for a candidate from their most recent match.

    Returns a dict with role facts (title, location, comp, JD text) that
    DeepSeek uses to answer candidate questions accurately and tailor
    screening questions to the role.
    """
    if not db:
        return None

    try:
        from app.models.match import Match
        from app.models.role import Role

        # Find most recent match for this candidate
        match = db.query(Match).filter(
            Match.candidate_id == candidate.id
        ).order_by(Match.created_at.desc()).first()

        if not match or not match.role_id:
            return None

        role = db.query(Role).filter(Role.id == match.role_id).first()
        if not role:
            return None

        comp_str = ''
        if role.comp_max:
            comp_str = f"up to ${role.comp_max // 1000}K"
        elif role.comp_min:
            comp_str = f"${role.comp_min // 1000}K+"

        return {
            'title': role.title,
            'company': role.company_name,
            'location_requirement': role.location_requirement.value if role.location_requirement else '',
            'location_cities': role.location_cities or [],
            'location_detail': '',  # could be parsed from JD
            'comp_str': comp_str,
            'jd_text': role.jd_text or '',
        }
    except Exception as e:
        logger.warning("Failed to get role context for candidate %s: %s", candidate.id, e)
        return None


def trigger_screening_questions_email(candidate, db=None):
    """
    Trigger the delayed screening questions email in background.

    Extracts primitive values from the candidate ORM object before spawning
    the background thread, so we don't depend on the request's DB session.

    Looks up the candidate's matched role to provide JD context for accurate
    question answering and tailored screening questions.
    """
    import threading

    candidate_id = candidate.id
    candidate_email = candidate.email
    candidate_name = candidate.name
    candidate_username = candidate.github_username
    outreach_subject = candidate.sent_outreach_subject or candidate.outreach_subject
    outreach_body = candidate.sent_outreach_body or candidate.outreach_body or ''
    reply_text = candidate.warmup_reply_text

    # Look up role context from the candidate's most recent match
    role_context = _get_role_context_for_candidate(candidate, db)
    if role_context:
        logger.info("Found role context for %s: %s (%s)", candidate_username, role_context.get('title'), role_context.get('location_requirement'))

    def run_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(send_followup_delayed(
            candidate_id, candidate_email, candidate_name,
            candidate_username, outreach_subject, reply_text,
            outreach_body=outreach_body, role_context=role_context
        ))
        loop.close()

    thread = threading.Thread(target=run_async)
    thread.daemon = True
    thread.start()

    logger.info("Scheduled screening questions email for %s (3 min delay)", candidate.email)


def trigger_screening_answer_processing(candidate, screening_reply_text, role_specific=False):
    """
    Trigger background processing of screening answers.

    Extracts primitive values from the candidate ORM object before spawning
    the background thread.
    """
    import threading

    candidate_id = candidate.id
    candidate_email = candidate.email
    candidate_name = candidate.name
    candidate_username = candidate.github_username
    outreach_subject = candidate.outreach_subject

    def run_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_screening_reply_delayed(
            candidate_id, candidate_email, candidate_name,
            candidate_username, outreach_subject, screening_reply_text,
            role_specific=role_specific
        ))
        loop.close()

    thread = threading.Thread(target=run_async)
    thread.daemon = True
    thread.start()

    logger.info("Scheduled screening answer processing for %s (2 min delay)", candidate.email)


# Keep old name as alias for backwards compatibility
trigger_screening_link_email = trigger_screening_questions_email
