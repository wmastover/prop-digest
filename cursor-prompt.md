# Build: Property Morning Digest v1 (ship tonight)

Build a small Python project that emails me a daily UK residential property digest at about 6am UK time on weekdays, built only from RSS feeds of news sites, and learns from my email replies. Deploy it on GitHub Actions. No servers, no databases, no web search. Keep it simple and finish it in one pass.

`property-digest-agent.md` is already in the repo root. It holds the editorial instructions and voice, and is the system prompt for the digest. Do not rewrite it, except for the preferences block described below.

## Stack
- Python 3.12, one `requirements.txt`: `openai`, `feedparser`, `pyyaml`, `python-dotenv`.
- All model calls go through **OpenRouter** using the `openai` SDK with `base_url="https://openrouter.ai/api/v1"` and `api_key=os.environ["OPENROUTER_API_KEY"]`. Model IDs are read from env vars `DIGEST_MODEL` and `FEEDBACK_MODEL` (defaults below). Check openrouter.ai/models for the current Anthropic Claude model IDs and use those as defaults: the latest Claude Sonnet for the digest, the latest Claude Haiku for feedback.
- Load secrets from `.env` locally (python-dotenv) and from GitHub secrets in Actions. Never hardcode a key, never print one, and make sure `.env` is in `.gitignore` before the first commit.
- Standard library `smtplib` and `imaplib` for Gmail (app password auth).
- GitHub Actions for scheduling and state. State lives as files committed back to the repo.

## Repo layout
```
property-digest-agent.md   # editorial instructions (exists)
feeds.yaml                 # RSS feeds
state/covered.json         # headlines + URLs sent in the last 14 days
state/last_run.txt         # ISO timestamp of the last successful run
digest.py                  # main entry point
feedback.py                # reply handling, called by digest.py first
.github/workflows/digest.yml
README.md                  # short setup steps
```

## feeds.yaml
```yaml
rss:
  - name: Property Industry EYE
    url: https://propertyindustryeye.com/feed
  - name: The Negotiator
    url: https://thenegotiator.co.uk/feed/
  - name: Property Week
    url: https://www.propertyweek.com/news/feed
  - name: BBC Business
    url: https://feeds.bbci.co.uk/news/business/rss.xml
    filter: true
  - name: Guardian Property
    url: https://www.theguardian.com/money/property/rss
```
- If any feed fails or returns nothing, log a warning and carry on. Never let one bad feed break the run.
- For feeds marked `filter: true`, keep only items whose title or summary contains one of: property, housing, house price, mortgage, rent, renter, landlord, estate agent, stamp duty, leasehold, Rightmove, Zoopla, housebuilder.

## Run order (digest.py)
1. **Feedback first.** Call `feedback.process()` (below).
2. **Gather.** Fetch all feeds. Keep items published since `last_run.txt` (if missing, use 24 hours ago; on Mondays use 72 hours). Normalise to `{title, url, source, published, summary}`, stripping HTML from summaries and truncating each to 600 characters. Drop any URL already in `state/covered.json`. Dedupe by URL. Cap at 60 items, newest first.
3. **If there are fewer than 3 items**, skip the model call and send a one-line email: "Quiet one. Nothing worth your time in the feeds today." Then save state and stop.
4. **Write the digest.** One chat completion call via OpenRouter:
   - Model: `DIGEST_MODEL`, max_tokens 4000.
   - System prompt: the full contents of `property-digest-agent.md`.
   - User message: today's date and weekday, the items as JSON, and a PREVIOUSLY COVERED list (headlines from `covered.json`).
   - Ask it to return only JSON: `{"subject": str, "html": str, "items": [{"headline": str, "url": str}]}`. Parse defensively (strip code fences; on failure retry once).
5. **Send.** Email via Gmail SMTP (smtp.gmail.com:465) from `GMAIL_ADDRESS` to `DIGEST_TO`, HTML body plus a plain-text fallback, with header `Reply-To:` set to `DIGEST_TO` with `+digest` inserted before the @ (e.g. `me+digest@googlemail.com`).
6. **Save state.** Append the sent items with today's date to `covered.json`, prune entries older than 14 days, write `last_run.txt`.
7. **Fail loudly.** If anything after step 1 throws, send a short plain-text email to `DIGEST_TO` with subject `[Prop Digest] FAILED` and the error, then exit non-zero.

## Feedback loop (feedback.py)
1. Connect to Gmail over IMAP (imap.gmail.com, same app password).
2. Search INBOX for unread messages sent TO the `+digest` address, FROM `DIGEST_TO` only. Ignore every other sender.
3. For each, extract only my new reply text (strip lines starting with `>`, and everything from a line matching `On ... wrote:` onwards).
4. If there is at least one reply, make one OpenRouter call with model `FEEDBACK_MODEL`: give it the current text between `<!-- PREFERENCES:START -->` and `<!-- PREFERENCES:END -->` plus my replies, and ask for an updated block of short bullets. It must merge and replace contradictory bullets rather than only appending, keep at most 20 bullets, and return only the bullets.
5. Replace only the text between those two markers in `property-digest-agent.md`. Never touch the rest of the file.
6. Send me one short confirmation email listing the new preferences.
7. Mark processed messages as read.

## Workflow (.github/workflows/digest.yml)
- Triggers: `schedule` with cron `30 5 * * 1-5` (UTC; GitHub Actions can run up to 30 minutes late, so this lands around 6am in UK winter time), plus `workflow_dispatch` for manual runs.
- `permissions: contents: write`.
- Steps: checkout, setup Python 3.12 with pip cache, install requirements, run `python digest.py`, then commit any changes to `state/` and `property-digest-agent.md` with message `digest: update state [skip ci]` and push. Only commit if there are changes.
- Secrets used: `OPENROUTER_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `DIGEST_TO`.

## Also
- Add a `--dry-run` flag that prints the subject and writes the HTML to `preview.html` instead of sending email or saving state (feedback is skipped too).
- Keep it under roughly 250 lines of Python total. No frameworks.
- README: the four secrets, how to create a Gmail app password, how to run manually from the Actions tab, and a note to change the cron to `30 4 * * 1-5` when UK clocks go forward.
- Test each feed URL first, drop any that return no items, and tell me which ones you dropped.
- When done, run `python digest.py --dry-run` locally using `.env`, and fix anything that breaks.

## Deploy (do all of this, don't stop at the code)
1. Check `gh auth status`. If the GitHub CLI isn't installed or logged in, stop and tell me exactly what command to run, then continue once I confirm.
2. If this folder isn't a git repo with a GitHub remote yet: `git init`, confirm `.env` is ignored (`git check-ignore .env` must succeed), commit, then `gh repo create prop-digest --private --source=. --push`.
3. Set the four secrets from `.env` with `gh secret set -f .env`. Never echo their values.
4. Trigger a run with `gh workflow run digest.yml`, wait for it with `gh run watch`, and read the logs with `gh run view --log-failed` if it fails.
5. If it fails, fix the cause, push, and run again. Repeat until a run passes. Don't declare it done on a failing or untested run.
6. Finish with a short report: repo URL, whether the test email was sent, which feeds were dropped, which model IDs you used, and anything I still need to do by hand.
