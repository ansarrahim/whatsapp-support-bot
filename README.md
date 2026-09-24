# WhatsApp AI Support Bot

A WhatsApp customer-support bot for small businesses (built here with a restaurant
FAQ set as the example). It answers common questions automatically, transcribes
voice notes, and routes anything it can't handle — complaints, refund requests,
or a direct "HUMAN" — to a real person by email. Runs as a single Python
function on Vercel.

`Flask` · `Google Gemini (google-genai)` · `Twilio WhatsApp` · `Upstash Redis` · `Vercel`

## What it does

1. A customer messages your WhatsApp number.
2. If it's a voice note, Gemini transcribes it first.
3. The message is classified: greeting, FAQ, or something that needs a human.
4. FAQ questions get answered from your own knowledge base (`data/faqs.json`) — the bot never invents information outside it.
5. Anything complex, a refund/complaint keyword, or the word "HUMAN" gets escalated by email to your team, and the customer gets an instant "connecting you with our team" reply.
6. Every conversation is remembered (last `MAX_HISTORY_MESSAGES` turns) so follow-up messages have context.
7. An admin dashboard at `/admin` shows real conversation stats — no fabricated numbers, including no fake "uptime" for what is a stateless deployment.

## Local setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # fill in whichever credentials you have — see below
python api/index.py    # runs on http://localhost:5000
```

**This app is designed to run and be testable with zero credentials configured** —
`/health` and `/admin` will work immediately, and `/webhook` will reply with a
graceful fallback message instead of crashing. Add credentials one at a time
as you get them; each one unlocks more of the real behavior. See `.env.example`
for exactly which file uses each variable and where to get it.

### Recommended order to get credentials

1. **`GOOGLE_API_KEY`** (free, no card, aistudio.google.com/apikey) — unlocks real FAQ answers and classification. You can test this locally with `curl` before touching Twilio at all:
   ```bash
   curl -X POST http://localhost:5000/webhook -d "Body=what are your hours" -d "From=whatsapp:+15551234567"
   ```
2. **Upstash Redis** (console.upstash.com, free tier) — makes conversation memory and dashboard stats persist across restarts instead of resetting.
3. **Twilio WhatsApp sandbox** (console.twilio.com) + **ngrok** — for a real WhatsApp round-trip. Join the sandbox from your phone with the code Twilio shows you, then point its webhook at `https://<your-ngrok-id>.ngrok-free.app/webhook`.
4. **Gmail App Password** (needs 2-Step Verification enabled first, myaccount.google.com/apppasswords) — enables real escalation emails.

Before deploying for real, double-check current Gemini model availability at
[ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models) —
`.env.example` ships with `gemini-2.5-flash` as the default, but Google's
model lineup changes quickly.

### Test messages to try once you have `GOOGLE_API_KEY`

| Message | Expected path |
|---|---|
| "hi" | Greeting reply |
| "what are your hours" | Real FAQ answer |
| "I want a refund, this is broken" | Escalated (keyword match) |
| "HUMAN" | Escalated (explicit request) |
| a voice note | Transcribed, then handled as the transcript |

## Deploying to Vercel

```bash
npm i -g vercel
vercel login
vercel link
vercel env add TWILIO_ACCOUNT_SID
vercel env add TWILIO_AUTH_TOKEN
vercel env add TWILIO_WHATSAPP_NUMBER
vercel env add GOOGLE_API_KEY
vercel env add GEMINI_CHAT_MODEL
vercel env add GEMINI_CLASSIFY_MODEL
vercel env add UPSTASH_REDIS_REST_URL
vercel env add UPSTASH_REDIS_REST_TOKEN
vercel env add GMAIL_USER
vercel env add GMAIL_APP_PASSWORD
vercel env add AGENT_EMAIL
vercel env add BOT_NAME
vercel env add MAX_HISTORY_MESSAGES
vercel env add ESCALATION_KEYWORDS
vercel env add ADMIN_PASSWORD
vercel --prod
```

After deploying, verify with `curl https://<your-domain>/health` — it returns
`missing_config` listing anything you haven't set yet, so you can see at a
glance what's left before going live. Then point your Twilio WhatsApp
number's webhook at `https://<your-domain>/webhook`.

## Environment variables

| Variable | Used by | Required for |
|---|---|---|
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | `api/index.py`, `bot/ai_client.py` | Real Twilio webhook, voice-note downloads |
| `TWILIO_WHATSAPP_NUMBER` | reference only | — |
| `GOOGLE_API_KEY` | `bot/ai_client.py` | FAQ answers, classification, transcription |
| `GEMINI_CHAT_MODEL` / `GEMINI_CLASSIFY_MODEL` | `bot/ai_client.py` | overriding the default model |
| `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` | `bot/memory.py` | persistent memory (falls back to in-process memory if unset) |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` / `AGENT_EMAIL` | `bot/handoff.py` | real escalation emails |
| `BOT_NAME` | `bot/responder.py`, dashboard | display name |
| `MAX_HISTORY_MESSAGES` | `bot/memory.py` | conversation memory length |
| `ESCALATION_KEYWORDS` | `bot/responder.py` | which words trigger human handoff |
| `ADMIN_PASSWORD` | `dashboard/routes.py` | unlocking `/admin` (HTTP Basic Auth, any username) |

## Security model

- **`/webhook` only accepts requests genuinely signed by Twilio.** Without
  `TWILIO_AUTH_TOKEN` set, every request is rejected (403) — the webhook is
  closed by default, not open until you configure it.
- **`/admin/*` requires `ADMIN_PASSWORD`** via HTTP Basic Auth. Unset means
  the whole dashboard, including the "clear conversation" action, is closed
  (401).
- **`/api/demo`** (the public landing-page chat widget) is rate-limited to
  `DEMO_RATE_LIMIT_PER_MINUTE` (default 5) requests per IP per minute, plus a
  300-character message cap — it calls the real Gemini API on your key, so
  it's a real cost surface, not just a style concern.

## Customizing the FAQ knowledge base

Edit `data/faqs.json` — each entry is `{"q", "a", "keywords"}`. The `keywords`
field isn't used for matching directly (classification is handled by Gemini),
it's there for your own reference when editing. The whole file is passed to
Gemini as grounding context, so keep it accurate — the bot is instructed to
say "not sure" and escalate rather than guess outside it.

## Pricing tiers (for offering this to clients)

- **Template** — $299: the codebase, set up with their own credentials
- **Done-for-you** — $900: fully configured, FAQ written, deployed, tested
- **Retainer** — $199/mo: ongoing FAQ updates, monitoring, escalation handling
