# Flight Ticket Extraction API

FastAPI service that accepts a **flight ticket PDF** or an **uploaded image** of a boarding pass/ticket and returns **structured JSON**, using **pdfplumber** with **OCR fallback** (pytesseract, pdf2image, PyMuPDF, OpenCV) and a **remote LLM** via an **OpenAI-compatible Chat Completions API**. You choose the provider and model (many hosts expose **open-weights** models such as Llama, Mistral, Qwen, etc.).

## Features

- `POST /extract` — multipart upload of a `.pdf` or an image (`.png/.jpg/.jpeg/.webp`)
- Pipeline: PDF/image → text (pdfplumber for PDFs, OCR fallback for scans) → text cleaning → regex hints (PNR, flight number) → LLM JSON extraction → Pydantic validation → up to **3** retries with a correction prompt
- **No local LLM weights** — calls `POST {LLM_API_BASE}/chat/completions` with your API key

## Prerequisites

1. **Python 3.10+**
2. **Tesseract OCR** (OCR fallback) — [Windows builds](https://github.com/UB-Mannheim/tesseract/wiki); ensure `tesseract` is on `PATH`.
3. **Poppler** (for `pdf2image`) — optional now. If Poppler is missing, the service falls back to **PyMuPDF** to rasterize PDFs for OCR.
4. An account with a provider that offers an **OpenAI-compatible** HTTP API (examples below).

## LLM configuration (required)

Set these **before** starting the server:

| Variable | Description |
|----------|--------------|
| `LLM_API_BASE` | Base URL including `/v1`, e.g. `https://api.groq.com/openai/v1` |
| `LLM_API_KEY` | Bearer token for that provider |
| `LLM_MODEL` | Model id as defined by the provider |

Optional:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MAX_TOKENS` | `500` | `max_tokens` in the chat request |
| `LLM_TEMPERATURE` | `0.1` | Sampling temperature |
| `LLM_TIMEOUT_SECONDS` | `120` | HTTP timeout for each LLM call |

### Example providers (open / open-weights models — check each site for current model ids)

**Groq** (fast inference; model list in their docs):

```powershell
$env:LLM_API_BASE = "https://api.groq.com/openai/v1"
$env:LLM_API_KEY = "gsk_..."
$env:LLM_MODEL = "llama-3.3-70b-versatile"
```

**Together AI:**

```powershell
$env:LLM_API_BASE = "https://api.together.xyz/v1"
$env:LLM_API_KEY = "..."
$env:LLM_MODEL = "meta-llama/Llama-3.1-8B-Instruct-Turbo"
```

**OpenRouter** (aggregates many models):

```powershell
$env:LLM_API_BASE = "https://openrouter.ai/api/v1"
$env:LLM_API_KEY = "sk-or-..."
$env:LLM_MODEL = "mistralai/mistral-7b-instruct:free"
```

Use whatever base URL and model id your provider documents for **Chat Completions**.

## Setup

```powershell
cd flight_api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

## Run

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000/docs** to try `POST /extract`.

## Deploying on Railway

You do **not** commit or upload `.venv`. Railway builds a fresh environment from `requirements.txt`.

1. **Root directory** — If the Git repo root is above this app folder, set Railway **Root Directory** to `flight_api` (the directory that contains `requirements.txt`, `app/`, and `Procfile`).
2. **Build** — Leave the build command **empty** unless you have a custom need; Nixpacks will run `pip install -r requirements.txt` automatically. `nixpacks.toml` installs **Tesseract** and **Poppler** (`aptPkgs`) so OCR works on Linux.
3. **Start** — Use the included `Procfile` (`web:`), or set **Custom Start Command** to:  
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`  
   Railway sets `$PORT`; binding to `0.0.0.0` is required.
4. **Variables** — In the Railway service, add `LLM_API_BASE`, `LLM_API_KEY`, and `LLM_MODEL` (and optional `LLM_*` tunables). Without them the app will fail at startup.

`runtime.txt` pins the Python line Nixpacks should use (adjust the patch version if needed).

## Deploying on Vercel

Use **`api/serve.py`** (ASGI `app`) + **`vercel.json`**. Set the Vercel project **Root Directory** to the folder that **contains** `api/`, `app/`, and `requirements.txt` (this `flight_api` directory). If the Root Directory is the parent repo (e.g. `LLM_OCR_API`) and there is no `api/` there, deploy will fail or `functions` patterns will not match.

`vercel.json` only rewrites traffic to `/api/serve`. Configure **Function max duration / memory** in the Vercel project settings if needed (a `functions` block with `api/index.py` often errors when that path is not part of the deployed tree).

1. **Environment variables** — Add `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` in Vercel → Settings → Environment Variables (Production). Redeploy after saving.
2. **Smoke test** — Open `https://<your-deployment>.vercel.app/` — expect `{"status":"ok",...}`. Then try `POST /extract`.
3. **Logs** — Vercel → your deployment → **Logs** (or Runtime Logs for the function) to see the real Python traceback for `FUNCTION_INVOCATION_FAILED`.
4. **Limits** — Serverless **timeouts** and **memory** are tight on the free tier; PDF + remote LLM may exceed them → upgrade plan or use Railway. **Tesseract** is usually **not** preinstalled on Vercel; with Poppler missing, OCR still works via **PyMuPDF** (but still needs Tesseract).
5. **`maxDuration` / `memory`** — Adjust in `vercel.json` within your team’s plan limits.

## Example `curl`

```bash
curl -X POST "http://localhost:8000/extract" -F "file=@ticket.pdf"
# or
curl -X POST "http://localhost:8000/extract" -F "file=@boarding_pass.png"
```

## Success response shape

```json
{
  "success": true,
  "message": "Ticket parsed successfully",
  "data": {
    "pnr": "",
    "bookingDate": "",
    "passengers": [
      {
        "passengerId": 1,
        "firstName": "",
        "lastName": "",
        "type": "",
        "ticketNumber": "",
        "seatNumber": ""
      }
    ],
    "flightDetails": [
      {
        "segmentId": 1,
        "airlineName": "",
        "airlineCode": "",
        "flightNumber": "",
        "departure": {
          "airportCode": "",
          "city": "",
          "terminal": "",
          "dateTime": ""
        },
        "arrival": {
          "airportCode": "",
          "city": "",
          "terminal": "",
          "dateTime": ""
        },
        "travelClass": "",
        "bookingClass": "",
        "status": ""
      }
    ]
  }
}
```

## Project layout

```
flight_api/
├── app/
│   ├── main.py
│   ├── routes.py
│   ├── pipeline.py
│   ├── services/
│   │   ├── pdf_service.py
│   │   ├── ocr_service.py
│   │   ├── llm_service.py
│   │   ├── regex_service.py
│   │   └── parser_service.py
│   ├── models/
│   │   └── schema.py
│   └── utils/
│       └── cleaner.py
├── requirements.txt
└── README.md
```

## Notes

- Startup only logs a warning at cold start; `/extract` still requires LLM env vars.
- If PDF text is short or empty, the service uses OCR automatically.
- Most extracted fields are **strings**; unknown values should be `""` when the model follows instructions (except numeric IDs like `passengerId`/`segmentId`).
