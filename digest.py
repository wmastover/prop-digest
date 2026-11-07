"""Property Morning Digest: RSS in, one HTML email out."""
import argparse
import calendar
import html
import json
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import yaml
from dotenv import load_dotenv

import feedback

ROOT = Path(__file__).parent
COVERED = ROOT / "state" / "covered.json"
LAST_RUN = ROOT / "state" / "last_run.txt"
ARCHIVE = ROOT / "archive"
AGENT_MD = ROOT / "property-digest-agent.md"
UK = ZoneInfo("Europe/London")
KEYWORDS = ["property", "housing", "house price", "mortgage", "rent", "renter", "landlord", "estate agent",
            "stamp duty", "leasehold", "rightmove", "zoopla", "housebuilder"]
UA = "Mozilla/5.0 (compatible; prop-digest/1.0)"
QUIET = "Quiet one. Nothing worth your time in the feeds today."
DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"
SECTIONS = {
    "Rules and politics": "🏛️",
    "The numbers": "📊",
    "Portals and big agencies": "🏢",
    "Who said what": "🗣️",
    "Challengers": "🥊",
    "PropTech money": "💰",
    "Elsewhere": "🌍",
}
MIN_WORDS, MAX_WORDS = 500, 800
FOOTER = "Reply to this email to change what you get."

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
S_WRAP = f"max-width:600px;margin:0 auto;padding:16px;font-family:{FONT};font-size:16px;line-height:1.6;color:#1a1a1a;"
S_OPENER = "margin:0 0 20px;font-size:17px;"
S_BIG = "margin:0 0 24px;padding:16px;background:#f4f6f8;border-left:4px solid #1a1a1a;"
S_LABEL = "margin:0 0 6px;font-size:12px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#666;"
S_H2 = "margin:28px 0 12px;font-size:19px;"
S_H3 = "margin:0 0 4px;font-size:16px;font-weight:bold;"
S_ITEM = "margin:0 0 18px;"
S_P = "margin:0;"
S_LINK = "color:#0b57d0;text-decoration:underline;"
S_LIST = "margin:0;padding-left:20px;"
S_SIGN = "margin:28px 0 4px;"
S_FOOT = "margin:0;font-size:13px;color:#666;"


def strip_html(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def load_covered():
    return json.loads(COVERED.read_text()) if COVERED.exists() else []


def since(now):
    if LAST_RUN.exists() and LAST_RUN.read_text().strip():
        return datetime.fromisoformat(LAST_RUN.read_text().strip())
    return now - timedelta(hours=72 if now.astimezone(UK).weekday() == 0 else 24)


def gather(now, covered):
    cutoff, seen = since(now), {c["url"] for c in covered}
    items = {}
    for feed in yaml.safe_load((ROOT / "feeds.yaml").read_text())["rss"]:
        try:
            parsed = feedparser.parse(feed["url"], agent=UA)
            if not parsed.entries:
                print(f"WARNING: {feed['name']} returned nothing ({parsed.get('bozo_exception', 'no items')})")
                continue
            for e in parsed.entries:
                stamp = e.get("published_parsed") or e.get("updated_parsed")
                url = e.get("link", "").strip()
                if not stamp or not url or url in seen or url in items:
                    continue
                published = datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc)
                title, summary = strip_html(e.get("title")), strip_html(e.get("summary"))[:600]
                if published < cutoff:
                    continue
                if feed.get("filter") and not any(k in f"{title} {summary}".lower() for k in KEYWORDS):
                    continue
                items[url] = {"title": title, "url": url, "source": feed["name"],
                              "published": published.isoformat(), "summary": summary}
        except Exception as exc:
            print(f"WARNING: feed {feed['name']} failed: {exc}")
    return sorted(items.values(), key=lambda i: i["published"], reverse=True)[:60]


def _str(value):
    return value.strip() if isinstance(value, str) else ""


def _story(raw, with_headline=True):
    if not isinstance(raw, dict) or not _str(raw.get("url")) or not _str(raw.get("text")):
        return None
    story = {"text": _str(raw["text"]), "url": _str(raw["url"]), "source": _str(raw.get("source"))}
    if with_headline:
        story["headline"] = _str(raw.get("headline"))
        if not story["headline"]:
            return None
    return story


def parse_content(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    data = json.loads(text[text.find("{"):text.rfind("}") + 1])
    big = _story(data.get("big_one"))
    if not _str(data.get("subject")) or big is None:
        raise ValueError("missing subject or big_one")
    order = list(SECTIONS)
    sections = []
    for s in data.get("sections") or []:
        if not isinstance(s, dict) or s.get("name") not in SECTIONS:
            continue
        items = [i for i in map(_story, s.get("items") or []) if i]
        if items:
            sections.append({"name": s["name"], "items": items})
    sections.sort(key=lambda s: order.index(s["name"]))
    return {
        "subject": _str(data["subject"]),
        "opener": _str(data.get("opener")),
        "big_one": big,
        "sections": sections,
        "quick_hits": [q for q in (_story(q, with_headline=False) for q in data.get("quick_hits") or []) if q][:4],
        "sign_off": _str(data.get("sign_off")),
    }


def stories(content):
    """Every story in the email as {section, headline, text, url, source}."""
    out = [{"section": "The big one", **content["big_one"]}]
    out += [{"section": s["name"], **i} for s in content["sections"] for i in s["items"]]
    out += [{"section": "Quick hits", "headline": q["text"], **q} for q in content["quick_hits"]]
    return out


def inline(text):
    escaped = html.escape(text, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def link(story):
    return f'<a href="{html.escape(story["url"])}" style="{S_LINK}">{html.escape(story["source"] or "Read more")}</a>'


def render_html(content):
    big = content["big_one"]
    parts = [f'<div style="{S_WRAP}">']
    if content["opener"]:
        parts.append(f'<p style="{S_OPENER}">{inline(content["opener"])}</p>')
    parts.append(
        f'<div style="{S_BIG}"><p style="{S_LABEL}">The big one</p>'
        f'<p style="{S_H3}">{inline(big["headline"])}</p>'
        f'<p style="{S_P}">{inline(big["text"])} {link(big)}</p></div>'
    )
    for s in content["sections"]:
        parts.append(f'<h2 style="{S_H2}">{SECTIONS[s["name"]]} {html.escape(s["name"])}</h2>')
        for i in s["items"]:
            parts.append(
                f'<div style="{S_ITEM}"><p style="{S_H3}">{inline(i["headline"])}</p>'
                f'<p style="{S_P}">{inline(i["text"])} {link(i)}</p></div>'
            )
    if content["quick_hits"]:
        parts.append(f'<h2 style="{S_H2}">⚡ Quick hits</h2><ul style="{S_LIST}">')
        parts += [f'<li style="margin:0 0 8px;">{inline(q["text"])} {link(q)}</li>' for q in content["quick_hits"]]
        parts.append("</ul>")
    if content["sign_off"]:
        parts.append(f'<p style="{S_SIGN}">{inline(content["sign_off"])}</p>')
    parts.append(f'<p style="{S_FOOT}">{FOOTER}</p></div>')
    return "\n".join(parts)


def render_text(content):
    plain = lambda t: t.replace("**", "")
    big = content["big_one"]
    lines = [plain(content["opener"]), "", "THE BIG ONE", plain(big["headline"]), f"{plain(big['text'])} ({big['url']})"]
    for s in content["sections"]:
        lines += ["", f"{SECTIONS[s['name']]} {s['name'].upper()}"]
        for i in s["items"]:
            lines += [plain(i["headline"]), f"{plain(i['text'])} ({i['url']})", ""]
    if content["quick_hits"]:
        lines += ["", "⚡ QUICK HITS"] + [f"- {plain(q['text'])} ({q['url']})" for q in content["quick_hits"]]
    lines += ["", plain(content["sign_off"]), FOOTER]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def banned_words():
    voice = AGENT_MD.read_text().split("## Voice", 1)[-1].split("\n## ", 1)[0]
    line = next((l for l in voice.splitlines() if "Ban:" in l), "")
    return re.findall(r'"([^"]+)"', line)


def word_count(content):
    texts = [content["opener"], content["sign_off"]]
    texts += [s.get("headline", "") + " " + s["text"] for s in stories(content)]
    texts += [s["name"] for s in content["sections"]]
    return len(" ".join(texts).replace("**", "").split())


def prose(content):
    texts = [content["subject"], content["opener"], content["sign_off"]]
    return "\n".join(texts + [s.get("headline", "") + "\n" + s["text"] for s in stories(content)])


def check(content, gathered_urls):
    problems = []
    text = prose(content)
    if "\u2014" in text:
        problems.append("contains em dashes (—); use full stops, commas or colons instead")
    lowered = text.lower()
    hits = [w for w in banned_words() if re.search(r"\b" + re.escape(w.lower()) + r"\w*", lowered)]
    if hits:
        problems.append("uses banned words: " + ", ".join(f'"{w}"' for w in hits))
    words = word_count(content)
    if not MIN_WORDS <= words <= MAX_WORDS:
        problems.append(f"is {words} words; it must be {MIN_WORDS} to {MAX_WORDS}")
    bad = sorted({s["url"] for s in stories(content)} - gathered_urls)
    if bad:
        problems.append("links to URLs that are not in ARTICLES (copy URLs exactly): " + ", ".join(bad))
    return problems


def recent_editions(n=2):
    editions = []
    for path in sorted(ARCHIVE.glob("*.json"), reverse=True):
        try:
            entry = json.loads(path.read_text())
        except Exception:
            continue
        if entry.get("test") or entry.get("quiet") or not entry.get("opener"):
            continue
        editions.append(entry)
        if len(editions) == n:
            break
    if not editions:
        return ""
    blocks = []
    for e in editions:
        heads = "\n".join(f"  - {s['headline']}" for s in e.get("stories", []) if s.get("section") != "Quick hits")
        blocks.append(f"{e['date']}\n  Opener: {e['opener']}\n  Headlines:\n{heads}")
    return "RECENT EDITIONS (match this voice, don't repeat these stories):\n" + "\n".join(blocks) + "\n\n"


def write_digest(items, covered, now, model):
    today = now.astimezone(UK)
    user = (
        f"Today is {today:%A %d %B %Y}.\n\nARTICLES (JSON):\n{json.dumps(items, indent=1)}\n\n"
        "PREVIOUSLY COVERED:\n" + ("\n".join(f"- {c['headline']}" for c in covered) or "(nothing)") + "\n\n"
        + recent_editions() +
        "Write today's digest following your instructions. Return ONLY the JSON object described in Format."
    )
    messages = [{"role": "system", "content": AGENT_MD.read_text()}, {"role": "user", "content": user}]
    client, urls = feedback.llm(), {i["url"] for i in items}
    best, last_err = None, None
    for attempt in range(2):
        resp = client.chat.completions.create(
            model=model, max_tokens=8000, messages=messages, extra_body=feedback.LOW_REASONING,
        )
        raw = resp.choices[0].message.content or ""
        try:
            content = parse_content(raw)
        except Exception as exc:
            last_err = exc
            print(f"WARNING: could not parse model output ({exc}), finish_reason={resp.choices[0].finish_reason}")
            note = f"That wasn't a valid JSON object in the Format described ({exc}). Return only the JSON object."
        else:
            problems = check(content, urls)
            best = (content, problems)
            if not problems:
                return best
            print(f"WARNING: attempt {attempt + 1} failed checks: {'; '.join(problems)}")
            note = "Your digest failed these checks: " + "; ".join(problems) + \
                ". Fix them and return the whole corrected JSON object only."
        messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": note}]
    if best is None:
        raise RuntimeError(f"model returned unparseable output twice: {last_err}")
    return best


def write_archive(now, entry, html_body):
    ARCHIVE.mkdir(exist_ok=True)
    day = now.astimezone(UK).date().isoformat()
    name = day
    if entry.get("test") and (ARCHIVE / f"{day}.json").exists():
        name = f"{day}-test"
    (ARCHIVE / f"{name}.json").write_text(json.dumps({"date": day, **entry}, indent=2, ensure_ascii=False) + "\n")
    (ARCHIVE / f"{name}.html").write_text(html_body + "\n")
    print(f"archived archive/{name}.json and .html")


def save_state(covered, sent, now):
    today = now.date().isoformat()
    covered += [{"headline": i.get("headline", ""), "url": i["url"], "date": today} for i in sent]
    cutoff = (now - timedelta(days=14)).date().isoformat()
    covered = [c for c in covered if c.get("date", today) >= cutoff]
    COVERED.parent.mkdir(exist_ok=True)
    COVERED.write_text(json.dumps(covered, indent=2) + "\n")
    LAST_RUN.write_text(now.isoformat() + "\n")


def run(dry_run, test):
    now = datetime.now(timezone.utc)
    config = yaml.safe_load((ROOT / "config.yaml").read_text()) if (ROOT / "config.yaml").exists() else {}
    model = os.environ.get("DIGEST_MODEL") or (config or {}).get("digest_model") or DEFAULT_MODEL
    prefix = "[TEST] " if test else ""
    covered = load_covered()
    items = gather(now, covered)
    print(f"gathered {len(items)} items, model {model}")
    if len(items) < 3:
        subject = f"{prefix}[Prop Digest] Quiet one"
        if dry_run:
            print(f"Subject: {subject}\n{QUIET}")
            return
        feedback.send_email(subject, QUIET)
        write_archive(now, {"subject": subject, "model": model, "gathered": len(items), "quiet": True,
                            "test": test, "stories": [], "problems": []}, f"<p>{QUIET}</p>")
        if not test:
            save_state(covered, [], now)
        return
    content, problems = write_digest(items, covered, now, model)
    subject = prefix + content["subject"]
    body = render_html(content)
    sent = stories(content)
    print(f"Subject: {subject}\n{len(sent)} stories, {word_count(content)} words")
    if problems:
        print(f"WARNING: sending despite failed checks: {'; '.join(problems)}")
    if dry_run:
        (ROOT / "preview.html").write_text(body)
        print("wrote preview.html")
        return
    extras = feedback.extra_recipients(config)
    sent_extra = feedback.send_digest(subject, render_text(content), body, feedback.reply_address(), extras)
    print(f"copies: 1 + {sent_extra} extra")
    write_archive(now, {"subject": subject, "model": model, "gathered": len(items), "test": test,
                        "opener": content["opener"], "stories": sent, "problems": problems,
                        "words": word_count(content)}, body)
    if not test:
        save_state(covered, sent, now)
    print(f"sent digest with {len(sent)} stories")


def main():
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print subject, write preview.html, send nothing")
    ap.add_argument("--test", action="store_true",
                    help="send a [TEST] email and archive it, but leave state/ alone so the next real run is unaffected")
    args = ap.parse_args()
    if not args.dry_run:
        try:
            feedback.process()
        except Exception as exc:
            print(f"WARNING: feedback step failed, carrying on: {exc}")
    try:
        run(args.dry_run, args.test)
    except Exception as exc:
        traceback.print_exc()
        if not args.dry_run:
            try:
                feedback.send_email("[Prop Digest] FAILED", f"The digest run failed:\n\n{exc!r}\n\n{traceback.format_exc()}")
            except Exception as mail_exc:
                print(f"could not send failure email: {mail_exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
