# Hackathon Evaluation

Judge console for the Lyzr Architect hackathon. Upload a submissions `.xlsx`, auto-fetch each app's
PRD / Lyra build log / Myra chat / agent graph from the Architect MongoDB, grade every row against
the 4-part rubric with OpenAI (GPT-4.1), and view a normalized leaderboard with per-criterion
justifications.

## Rubric (100 pts)

| # | Criterion             | Max |
|---|-----------------------|-----|
| 1 | Problem Clarity       | 25  |
| 2 | Agentic Complexity    | 25  |
| 3 | Live Functionality    | 25  |
| 4 | Business Impact       | 25  |

### Scoring

- `raw_total` — OpenAI score against the rubric (0-100, absolute)
- `percentile` — rank percentile within the uploaded batch (0-100, relative)
- `final_score` — `0.7 * raw_total + 0.3 * percentile`

Final keeps absolute quality dominant while giving the top builders a normalized lift so they
separate cleanly from the pack.

## Run locally

```bash
cd hackathon-evaluation
cp .env.example .env        # fill in DB_URL + OPENAI_API_KEY
./run.sh
```

Then open [http://localhost:8010](http://localhost:8010).

## Data flow

1. User uploads `.xlsx` → backend parses rows (column order doesn't matter, aliases handled).
2. For each row's `app_id`, the backend queries MongoDB `apps` collection (the same DB the
   `architect-backend` writes to) and extracts:
   - Input prompt (first user message in `state.myraChatMessages`)
   - PRD excerpt (longest assistant message that looks like a PRD)
   - Condensed Myra chat (5000 chars)
   - Condensed Lyra build log with error highlighting (4000 chars)
   - Agent graph (name, model, tools)
   - Deployment info, commit count, message counts
3. Each submission is sent to OpenAI with strict JSON output enforced. Parallelism = 5.
4. Scores are normalized across the batch and returned in ranked order.

## Files

```
hackathon-evaluation/
├── backend/
│   ├── main.py        FastAPI app: serves landing page + API
│   ├── db.py          MongoDB connection (DB_URL / DB_NAME)
│   ├── extractor.py   _extract_tier1, _extract_prd, condense_messages
│   ├── parser.py      Excel parsing (openpyxl) with column aliasing
│   ├── scorer.py      OpenAI rubric + normalize_batch
│   └── make_sample.py Generates sample_submissions.xlsx
├── frontend/
│   ├── index.html     Landing page (diane-final.html theme)
│   ├── styles.css     Design tokens lifted from the template
│   └── app.js         Upload, parse, evaluate, render, export
├── sample_submissions.xlsx   (generated)
├── requirements.txt
├── run.sh
└── .env.example
```

## API

| Method | Path                   | Purpose                                    |
|--------|------------------------|--------------------------------------------|
| GET    | `/api/health`          | Health + config check                      |
| GET    | `/api/rubric`          | Rubric JSON                                |
| GET    | `/api/app/{app_id}`    | Debug: extracted context for one app       |
| POST   | `/api/parse`           | Parse xlsx → return rows (no scoring)      |
| POST   | `/api/evaluate`        | Parse + fetch + score + normalize          |
| GET    | `/api/sample-excel`    | Download sample xlsx                       |

## Testing with a real app

The sample xlsx ships with real app id `69e7161fff1ef4a43123e111` on row 1.
Rows 2–4 use fake ids to exercise the "app not found" fallback.

Hit `/api/app/69e7161fff1ef4a43123e111` in your browser (once the server is running and DB_URL
points to the production MongoDB) to confirm the extractor is returning real data before running
a full evaluation.

## Deploy to Railway

The repo is Dockerfile-ready. In Railway:

1. **New Service → Deploy from GitHub repo** → pick `hackathon-evaluation`. Railway will use the `Dockerfile` automatically (the `railway.json` pins this).

2. **Add a volume** at `/data` (Service → Settings → Volumes → New Volume, mount path `/data`). This persists `runs.db` and the decoded Mongo TLS cert across restarts.

3. **Set these environment variables** (Service → Variables):

   ```
   DB_URL                = mongodb://user:pass@host:27017/...&tlsCAFile=/data/cred.pem&...
   DB_NAME               = lyzr-engineer
   OPENAI_API_KEY        = sk-...
   OPENAI_MODEL          = gpt-4.1
   MONGO_TLS_CA_B64      = <base64 of your cred.pem>
   ```

   To generate `MONGO_TLS_CA_B64` locally:
   ```bash
   base64 -i /Users/suyashmankar/Desktop/LYZR/cred.pem | tr -d '\n' | pbcopy
   ```

   On startup, `backend/bootstrap.py` decodes that env var to `/data/cred.pem` and rewrites the `tlsCAFile=...` segment of `DB_URL` to match — so the DB_URL you paste can keep any placeholder path; the code normalizes it.

4. **Generate a public domain** (Settings → Networking → Generate Domain). Railway injects `$PORT`; the Dockerfile binds to it.

5. **Lock it down.** This tool reads your whole prod DB. At minimum add HTTP basic auth (a short FastAPI middleware) or put it behind Cloudflare Access before sharing the URL.

## Notes on scoring discipline

The system prompt instructs the judge to:
- Cap `live_functionality` at 8 if there is no deployment URL.
- Cap `agentic_complexity` at 12 for single-agent apps.
- Cap `problem_clarity` at 12 if the input prompt/PRD and user-claimed pain-point are all vague.
- Penalize hype language not supported by the actual app data.
- Reserve 85+ for genuinely exceptional work; expect most submissions to land 50-75.

This keeps the batch distribution honest so normalization is meaningful.
