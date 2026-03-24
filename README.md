# Flight Ticket Extraction API

FastAPI service that accepts a **flight ticket PDF** and returns **structured JSON**, using **pdfplumber** with **OCR fallback** (pytesseract, pdf2image, OpenCV) and a **remote LLM** via an **OpenAI-compatible Chat Completions API**. You choose the provider and model (many hosts expose **open-weights** models such as Llama, Mistral, Qwen, etc.).

## Features

- `POST /extract` — multipart upload of a `.pdf` file
- Pipeline: PDF → text (pdfplumber) → optional OCR → text cleaning → regex hints (PNR, flight number) → LLM JSON extraction → Pydantic validation → up to **3** retries with a correction prompt
- **No local LLM weights** — calls `POST {LLM_API_BASE}/chat/completions` with your API key

## Prerequisites

1. **Python 3.10+**
2. **Tesseract OCR** (OCR fallback) — [Windows builds](https://github.com/UB-Mannheim/tesseract/wiki); ensure `tesseract` is on `PATH`.
3. **Poppler** (for `pdf2image`) — required to rasterize PDFs for OCR.
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

## Example `curl`

```bash
curl -X POST "http://localhost:8000/extract" -F "file=@ticket.pdf"
```

## Success response shape

```json
{
  "status": "success",
  "data": {
    "passenger_name": "",
    "pnr": "",
    "airline": "",
    "flight_number": "",
    "departure_airport": "",
    "arrival_airport": "",
    "departure_time": "",
    "arrival_time": "",
    "date": "",
    "seat": "",
    "gate": "",
    "price": ""
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

- Startup **fails fast** if `LLM_API_BASE`, `LLM_API_KEY`, or `LLM_MODEL` is missing.
- If PDF text is short or empty, the service uses OCR automatically.
- All extracted fields are **strings**; unknown values should be `""` when the model follows instructions.
