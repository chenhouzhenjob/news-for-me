# news-for-me

Daily Chinese AI news email automation.

## What it does

`ai_daily_report.py`:

1. Uses `Asia/Shanghai` by default and reports on "yesterday" from 00:00:00 to 23:59:59.
2. Collects AI news from official company blogs, trusted AI/tech media RSS feeds, arXiv, and GitHub project discovery.
3. Prioritizes high-impact model/product releases, company updates, papers, open-source projects, funding, infrastructure, and regulation.
4. Generates a Chinese email with 5-10 headline bullets, ranked detail cards, clickable source links, image links or screenshot/display suggestions, and extended reading.
5. Sends both plain-text Markdown and styled HTML email through SMTP.

The script does not invent links or facts. If a source cannot be fetched, the email includes a collection note.

## Default configuration

- `RECIPIENT_EMAIL`: configured through environment variables or repository secrets
- `TIMEZONE`: `Asia/Shanghai`
- `AI_MAX_ITEMS`: `12`
- `AI_FETCH_ARTICLE_IMAGES`: `true`

## Required environment variables

Email delivery:

- `SMTP_HOST`
- `SMTP_PORT` (usually `587` or `465`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- Optional: `SMTP_FROM`
- Optional: `RECIPIENT_EMAIL` or `EMAIL_TO`

GitHub Actions uses repository secrets/variables with the same names. The workflow is configured to run at `0 0 * * *` UTC, which is 08:00 in Beijing.

## Run locally

Dry run and write HTML output:

```bash
python3 ai_daily_report.py --dry-run --output report.html
```

Send the email:

```bash
python3 ai_daily_report.py
```

Send a test email with a `【测试】` prefix in the subject:

```bash
python3 ai_daily_report.py --test
```

Generate a report for a specific Beijing date:

```bash
python3 ai_daily_report.py --date 2026-06-24 --dry-run
```

## Legacy script

`twitter_daily_report.py` is kept for manual Twitter/X account reports, but the scheduled workflow now sends the AI daily report.
