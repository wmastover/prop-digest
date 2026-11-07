"""Reply handling: read +digest replies from Gmail and update the preferences block."""
import email
import imaplib
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).parent
AGENT_MD = ROOT / "property-digest-agent.md"
START, END = "<!-- PREFERENCES:START -->", "<!-- PREFERENCES:END -->"
# Current Claude models on OpenRouter think by default (and Sonnet can't turn it off), which can eat all of max_tokens.
LOW_REASONING = {"reasoning": {"effort": "low"}}


def llm():
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])


def reply_address():
    user, domain = os.environ["DIGEST_TO"].split("@", 1)
    return f"{user}+digest@{domain}"


def extra_recipients(config=None):
    """Addresses that get their own copy of the daily digest. DIGEST_TO is never included."""
    found = []
    found.extend(os.environ.get("EXTRA_RECIPIENTS", "").replace(";", ",").split(","))
    found.extend((config or {}).get("extra_recipients") or [])
    me = os.environ.get("DIGEST_TO", "").strip().lower()
    out, seen = [], set()
    for raw in found:
        addr = str(raw).strip()
        key = addr.lower()
        if not addr or "@" not in addr or key == me or key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


def send_email(subject, text, html=None, reply_to=None, to=None):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ["GMAIL_ADDRESS"], to or os.environ["DIGEST_TO"]
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)


def send_digest(subject, text, html, reply_to, extras=()):
    """One copy per recipient, so nobody sees the others. Extras failing does not fail the run."""
    send_email(subject, text, html, reply_to)
    sent = 0
    for addr in extras:
        try:
            send_email(subject, text, html, reply_to, to=addr)
        except Exception as exc:
            print(f"WARNING: an extra copy failed to send ({type(exc).__name__})")
        else:
            sent += 1
    return sent


def reply_text(msg):
    part = next((p for p in msg.walk() if p.get_content_type() == "text/plain"
                 and "attachment" not in str(p.get("Content-Disposition", ""))), None)
    if part is None:
        return ""
    body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
    lines, raw = [], body.splitlines()
    for n, line in enumerate(raw):
        # Gmail sometimes wraps the "On ... wrote:" attribution over two lines.
        pair = line + " " + (raw[n + 1] if n + 1 < len(raw) else "")
        if re.match(r"^\s*On\b.*wrote:\s*$", line) or (line.lstrip().startswith("On ") and pair.rstrip().endswith("wrote:")):
            break
        if not line.lstrip().startswith(">"):
            lines.append(line)
    return "\n".join(lines).strip()


def process():
    me = os.environ["DIGEST_TO"].lower()
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    try:
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN", "TO", f'"{reply_address()}"', "FROM", f'"{me}"')
        ids, replies = data[0].split(), []
        for i in ids:
            _, raw = imap.fetch(i, "(BODY.PEEK[])")
            msg = email.message_from_bytes(raw[0][1])
            if parseaddr(msg.get("From", ""))[1].lower() != me:
                continue
            if reply_address().lower() not in str(msg.get("To", "")).lower():
                continue
            text = reply_text(msg)
            if text:
                replies.append(text)
        if replies:
            update_preferences(replies)
        for i in ids:
            imap.store(i, "+FLAGS", "\\Seen")
        print(f"feedback: {len(replies)} repl{'y' if len(replies) == 1 else 'ies'} processed")
    finally:
        imap.logout()


def update_preferences(replies):
    doc = AGENT_MD.read_text()
    head, rest = doc.split(START, 1)
    current, tail = rest.split(END, 1)
    prompt = (
        "You maintain a reader's preferences for a daily UK property news digest.\n\n"
        f"CURRENT PREFERENCES:\n{current.strip()}\n\nNEW REPLIES FROM THE READER:\n"
        + "\n---\n".join(replies)
        + "\n\nReturn an updated list of short bullet points (each starting with '- '). Merge duplicates, "
        "replace bullets the new replies contradict rather than keeping both, ignore anything that isn't a "
        "preference, and keep at most 20 bullets. Return only the bullets, nothing else."
    )
    resp = llm().chat.completions.create(
        model=os.environ.get("FEEDBACK_MODEL", "anthropic/claude-haiku-5.5"),
        max_tokens=1000, messages=[{"role": "user", "content": prompt}], extra_body=LOW_REASONING,
    )
    bullets = [l.strip() for l in resp.choices[0].message.content.splitlines() if l.strip().startswith(("-", "*"))]
    bullets = ["- " + b.lstrip("-* ").strip() for b in bullets][:20] or ["- (none yet)"]
    block = "\n".join(bullets)
    AGENT_MD.write_text(f"{head}{START}\n{block}\n{END}{tail}")
    send_email("[Prop Digest] Preferences updated", "Got it. Your digest preferences are now:\n\n" + block)
