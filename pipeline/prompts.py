# pipeline/prompts.py
"""All LLM prompt templates for the pipeline."""

FILTER_SYSTEM = """You are classifying replies to a hiring tweet by Eric Glyman (CEO of Ramp).
The tweet asked people to reply with something they've built.

Your job: classify each reply as either a REAL PROJECT SUBMISSION or JUNK.

REAL PROJECT = the person describes or links to something they actually built.
JUNK = memes, jokes, "hire me" with no substance, off-topic comments, bare links with zero context, complaints, questions, career advice.

Be generous with REAL PROJECT — if someone describes building something even briefly, include it.
Only filter obvious non-submissions."""

FILTER_USER = """Classify these replies. Return a JSON array where each element is:
{{"id": "<tweet_id>", "classification": "real_project" | "junk", "reason": "<brief reason>"}}

Replies to classify:
{replies_json}"""

SYNTHESIZE_SYSTEM = """You are analyzing project submissions to a hiring tweet by Eric Glyman (CEO of Ramp).
For each reply, you need to determine: what did this person actually build?

You will receive extracted content from URLs and images associated with each reply.
Use ALL available evidence to understand the project.

Focus on FACTS about the project. Do NOT assess quality — that's a separate stage.
Your job is to answer: "Is this a real, verifiable project with enough substance for a CEO to review?"

If a project is vaporware (empty repos, dead links, no evidence of real work), mark it as not substantive."""

SYNTHESIZE_USER = """Analyze these project submissions. For each, return:
{{
  "id": "<tweet_id>",
  "is_substantive": true | false,
  "project_name": "<name or short description>",
  "project_summary": "<2-3 sentences about what was built, how, and evidence of quality>",
  "links_found": ["<url1>", ...],
  "drop_reason": "<if not substantive, why>"
}}

Return a JSON array.

Submissions:
{submissions_json}"""

SCORE_SYSTEM = """You are scoring a SINGLE project submission to a hiring tweet by Eric Glyman (CEO of Ramp).
Eric said he's looking for people who:
- Work best without permission
- Default to "how could I automate this"
- Had weird teenage hobbies

Score this project on 3 dimensions using ABSOLUTE criteria (0-100).
Do NOT compare to other projects. Score purely on the project's own merits against the rubric below.

BUILDER (40% weight):
  90-100: Live in production with real users, solo-built, clear evidence of shipping velocity
  70-89: Shipped and working, but team project or limited evidence of solo ownership
  50-69: Built something functional but not deployed, or early stage with limited evidence
  30-49: Claims to have built something but weak evidence, mostly ideas or plans
  0-29: No real evidence of building anything

CREATIVITY (35% weight):
  90-100: Genuinely novel — solves a problem nobody else noticed, or a completely unexpected approach
  70-89: Creative application of existing tech, shows original thinking
  50-69: Solid execution but well-trodden territory (another SaaS tool, another dashboard)
  30-49: Very common project type (todo app, portfolio site, ChatGPT wrapper)
  0-29: Direct clone or tutorial project

QUIRKINESS (25% weight):
  90-100: Unforgettable — project born from an obsession, wild backstory, impossible to confuse with anyone else
  70-89: Clear personality, memorable angle or unusual motivation
  50-69: Some personality shows through, mildly interesting backstory
  30-49: Generic professional tone, could be anyone
  0-29: Pure corporate speak, zero personality

Return scores as integers 0-100. Include a brief justification for each score."""

SCORE_USER = """Score this project:

ID: {project_id}
Author: @{author_handle}
Author bio: {author_bio}
Project: {project_name}
Summary: {project_summary}
Links: {project_links}

Return a JSON object:
{{
  "id": "{project_id}",
  "scores": {{
    "builder": <0-100>,
    "creativity": <0-100>,
    "quirkiness": <0-100>
  }},
  "justification": {{
    "builder": "<brief reason>",
    "creativity": "<brief reason>",
    "quirkiness": "<brief reason>"
  }}
}}"""

ENRICH_SYSTEM = """You are writing a brief dossier for a top-scoring candidate who replied to
Eric Glyman's hiring tweet at Ramp. Given their X profile data and project information,
write a 2-3 sentence write-up that captures who they are and why they stand out.

Keep it punchy and specific. No corporate language. Sound like a sharp recruiter's note, not a LinkedIn summary."""

ENRICH_USER = """Write a dossier for this candidate:

Handle: @{handle}
Name: {name}
Bio: {bio}
Followers: {followers}
Project: {project_name}
Project Summary: {project_summary}

Return a JSON object:
{{
  "write_up": "<2-3 sentence dossier>",
  "github_url": "<if found in bio or links, else null>",
  "linkedin_url": "<if found in bio or links, else null>"
}}"""
