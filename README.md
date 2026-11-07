# Property Morning Digest

Emails a daily UK residential property digest around 6am UK time on weekdays, built from the RSS feeds in `feeds.yaml` and written by Claude via OpenRouter. Reply to a digest to change what you get: replies are folded into the preferences block at the bottom of `property-digest-agent.md`. Planned features are in [ROADMAP.md](ROADMAP.md).

## Secrets

Add these under **Settings → Secrets and variables → Actions** (or `gh secret set -f .env`):

| Secret | What it is |
| --- | --- |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `GMAIL_ADDRESS` | Gmail account the digest is sent from |
| `GMAIL_APP_PASSWORD` | Gmail app password for that account |
| `DIGEST_TO` | Where the digest goes. Replies go to this address with `+digest` added, so it should be the same mailbox as `GMAIL_ADDRESS` for the feedback loop to see them |
| `EXTRA_RECIPIENTS` | Optional. Comma-separated addresses that each get their own copy of the daily digest. They are not on each other's emails. Quiet-day, failure, and preference emails still go only to `DIGEST_TO`, and only replies from `DIGEST_TO` update preferences. While the repo is public, keep addresses here rather than in `config.yaml` |

The digest model is set in `config.yaml` (currently Haiku). Change settings there rather than in the workflow file. `DIGEST_MODEL` and `FEEDBACK_MODEL` (default `anthropic/claude-haiku-5.5`) env vars still override.

## Gmail app password

1. Turn on 2-Step Verification for the Google account.
2. Go to <https://myaccount.google.com/apppasswords>, create an app password (any name, e.g. "Prop Digest").
3. Use the 16-character password as `GMAIL_APP_PASSWORD`. IMAP must be enabled (it is by default on current Gmail).

## Running

- **Manually:** Actions tab → *Property Morning Digest* → **Run workflow**.
- **Locally:** put the four values in `.env`, `pip install -r requirements.txt`, then `python digest.py --dry-run` (prints the subject and writes `preview.html`; sends nothing, skips feedback, saves no state).

- **Test send:** `python digest.py --test` sends a `[TEST]` email and archives it, but leaves `state/` alone so the next real run is unaffected.

The model returns content only (JSON); `digest.py` checks it (no em dashes, no banned words, 500 to 800 words, links only to gathered articles, one retry on failure) and lays it out from a fixed template.

State (`state/covered.json`, `state/last_run.txt`), preference updates and the archive are committed back to the repo after each run. `archive/YYYY-MM-DD.json` holds each edition's subject, model, stories and any failed checks; `archive/YYYY-MM-DD.html` is the exact email sent. The archive is never pruned.

## Clocks

The crons in `.github/workflows/digest.yml` are in UTC and land around 6am UK winter time. When UK clocks go forward in March, move both an hour earlier, and back again in October. Edit them yourself on GitHub: scheduled runs belong to whoever last changed the cron lines, and they don't fire when that was a bot.
