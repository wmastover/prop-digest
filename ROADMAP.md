# Roadmap

A simple backlog. One short entry per feature; bigger ones get a fuller write-up below.

## Next

- **People spotlight.** A short "Who's this?" block for key people mentioned in an edition. See [People spotlight](#people-spotlight) below.
- **Make the repo private.** It's public, so the prompt, state and every archived email are readable by anyone. Settings → General → Danger Zone → Change visibility.
- **Test the quiet-day and FAILED email paths.** Neither has run for real yet. Force each once with `--test` (e.g. an empty `feeds.yaml` for quiet, a bad model ID for FAILED) and check both emails arrive and look right.

## Later

- **External cron as a backup trigger.** A cron-job.org job (Mon–Fri 05:25 Europe/London) calls the `workflow_dispatch` API with `{"ref":"main","inputs":{"once_per_day":"true"}}`, using a fine-grained token scoped to this repo with Actions: Read and write. The once-per-day guard makes it safe alongside GitHub's schedule. Free; about 10 minutes to set up; the token needs renewing when it expires.
- **Clocks go forward (BST).** On the last Sunday of March, move both crons in `digest.yml` an hour earlier (`18 4` and `47 5`), and back in late October. Edit them yourself on GitHub, because the schedule only fires when a real user made the last cron change. The external cron above would handle this automatically via its timezone setting.
- **Sonnet as an option.** Set `DIGEST_MODEL: anthropic/claude-sonnet-5.5` in `digest.yml` for sharper writing. Roughly 20p a day versus about 1p on Haiku. Worth a week's side-by-side using the archive.

## Ideas

- (add here)

---

## People spotlight

When an edition mentions a key person, add a short **Who's this?** block next to the story:

- **Who they are:** name, role and organisation.
- **LinkedIn:** a link so you can check them in one click.
- **Photo:** optional.
- **Relevance:** one line on whether they matter to your business and whether they're worth messaging.

### Constraints

- **No live lookups.** The digest only sees RSS text and can't browse, so it can't look anyone up. Everything about a person has to come from the article itself or from a list we keep. Nothing may be invented: no guessed roles, employers or profile links.
- **LinkedIn blocks scraping.** Profile details and photos can't be fetched automatically, and trying risks the account.
- **Names are ambiguous.** "James Smith" in an article isn't necessarily the James Smith on the list. A match should need name plus organisation, or name plus a clear role, from the article text.

### How it would work

1. **A curated `people.yaml`** with name, role, org, LinkedIn URL, tier, why they matter, and an optional photo URL. Seed it from the People tab of `property-digest-sources.xlsx`: 20 people with tiers, but the organisations are marked "verify" and the LinkedIn column is still empty, so this needs a one-off pass by you, about 30 minutes.
2. **Matching in Python.** After the model writes the edition, scan each story for names in `people.yaml`, and require the organisation (or an alias) to appear too. Python, not the model, decides who matched, so links and facts always come from the list.
3. **People not on the list.** For a named senior figure the model flags, such as someone quoted with a job title, show only what the article says. Add a LinkedIn people-search link built from name plus org (`https://www.linkedin.com/search/results/people/?keywords=<name>%20<org>`) rather than a guessed profile URL.
4. **Writing the block.** Either a fixed template filled from `people.yaml` (zero cost, fully predictable), or a single extra Haiku call that writes the relevance line from the curated "why they matter" plus the story. The model gets only the curated fields and the article text, and must not add anything else.
5. **Photos.** Only from a `photo` URL you add by hand to `people.yaml`. With no URL, there's no photo. Some email clients block remote images anyway.
6. **"Add this person" by reply.** Extend the existing feedback loop so a reply like `add person: Jane Doe, CEO, Acme Lettings, https://linkedin.com/in/..., tier 2, why: runs the biggest BTR lettings book` is parsed and appended to `people.yaml`. The confirmation email shows exactly what was saved. Replies that aren't in that format keep going to preferences as now.

### Cost and effort

- **Running cost:** close to nothing. Template-only is free. With the Haiku relevance line, it's about 1,000 to 2,000 extra tokens per edition, well under 1p a day.
- **Build:** small to medium.
  - `people.yaml` and its loader.
  - Matching with an organisation check.
  - The block in the email template and plain-text version.
  - An archive field listing who was spotlighted.
  - The reply parser in `feedback.py`.
  - Tests for false matches.
  - All self-contained in `digest.py` and `feedback.py`, with no new services or dependencies.
- **Your time:** about 30 minutes to fill in LinkedIn URLs and check organisations for the 20 seeded people, then occasional replies to add new ones.
