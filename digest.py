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
KEYWORDS = ["property", "housing", "house price", "mortgage", "rent", "renter", "landlord", "estate agent",
            "stamp duty", "leasehold", "rightmove", "zoopla", "housebuilder"]
UA = "Mozilla/5.0 (compatible; prop-digest/1.0)"
QUIET = "Quiet one. Nothing worth your time in the feeds today."


def strip_html(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def html_to_text(body):
    body = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", body, flags=re.S | re.I)
    body = re.sub(r"<(br|/p|/h\d|/li|/div|/tr)[^>]*>", "\n", body, flags=re.I)
    lines = (re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", "", l))).strip() for l in body.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def load_covered():
    return json.loads(COVERED.read_text()) if COVERED.exists() else []


def since(now):
    if LAST_RUN.exists() and LAST_RUN.read_text().strip():
        return datetime.fromisoformat(LAST_RUN.read_text().strip())
    return now - timedelta(hours=72 if now.astimezone(ZoneInfo("Europe/London")).weekday() == 0 else 24)


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


def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start:end + 1])
    if not isinstance(data.get("subject"), str) or not isinstance(data.get("html"), str):
        raise ValueError("missing subject or html")
    data["items"] = [i for i in data.get("items", []) if isinstance(i, dict) and i.get("url")]
    return data


def write_digest(items, covered, now):
    today = now.astimezone(ZoneInfo("Europe/London"))
    user = (
        f"Today is {today:%A %d %B %Y}.\n\nARTICLES (JSON):\n{json.dumps(items, indent=1)}\n\n"
        "PREVIOUSLY COVERED:\n" + ("\n".join(f"- {c['headline']}" for c in covered) or "(nothing)") + "\n\n"
        "Write today's digest following your instructions. Return ONLY a JSON object, no code fences, of the form "
        '{"subject": str, "html": str, "items": [{"headline": str, "url": str}]} where items lists every '
        "story you included, with the URL you linked."
    )
    system = (ROOT / "property-digest-agent.md").read_text()
    client, last_err = feedback.llm(), None
    for _ in range(2):
        resp = client.chat.completions.create(
            model=os.environ.get("DIGEST_MODEL", "anthropic/claude-sonnet-5.5"), max_tokens=8000,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            extra_body=feedback.LOW_REASONING,
        )
        try:
            return parse_json(resp.choices[0].message.content or "")
        except Exception as exc:
            last_err = exc
            print(f"WARNING: could not parse model output ({exc}), finish_reason={resp.choices[0].finish_reason}")
    raise RuntimeError(f"model returned unparseable output twice: {last_err}")


def save_state(covered, sent, now):
    today = now.date().isoformat()
    covered += [{"headline": i.get("headline", ""), "url": i["url"], "date": today} for i in sent]
    cutoff = (now - timedelta(days=14)).date().isoformat()
    covered = [c for c in covered if c.get("date", today) >= cutoff]
    COVERED.parent.mkdir(exist_ok=True)
    COVERED.write_text(json.dumps(covered, indent=2) + "\n")
    LAST_RUN.write_text(now.isoformat() + "\n")


def run(dry_run):
    now = datetime.now(timezone.utc)
    covered = load_covered()
    items = gather(now, covered)
    print(f"gathered {len(items)} items")
    if len(items) < 3:
        if dry_run:
            print(f"Subject: [Prop Digest] Quiet one\n{QUIET}")
            return
        feedback.send_email("[Prop Digest] Quiet one", QUIET)
        save_state(covered, [], now)
        return
    digest = write_digest(items, covered, now)
    print(f"Subject: {digest['subject']}")
    if dry_run:
        (ROOT / "preview.html").write_text(digest["html"])
        print(f"wrote preview.html ({len(digest['items'])} stories)")
        return
    feedback.send_email(digest["subject"], html_to_text(digest["html"]), digest["html"], feedback.reply_address())
    save_state(covered, digest["items"], now)
    print(f"sent digest with {len(digest['items'])} stories")


def main():
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print subject, write preview.html, send nothing")
    dry_run = ap.parse_args().dry_run
    if not dry_run:
        try:
            feedback.process()
        except Exception as exc:
            print(f"WARNING: feedback step failed, carrying on: {exc}")
    try:
        run(dry_run)
    except Exception as exc:
        traceback.print_exc()
        if not dry_run:
            try:
                feedback.send_email("[Prop Digest] FAILED", f"The digest run failed:\n\n{exc!r}\n\n{traceback.format_exc()}")
            except Exception as mail_exc:
                print(f"could not send failure email: {mail_exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
