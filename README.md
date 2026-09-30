# Smart Waste Collection Optimizer (BIT-29)

Streamlit dashboard -> FastAPI backend (Render) -> Supabase Postgres.

## One-time setup
1. **Supabase**: SQL Editor -> paste `schema.sql` -> Run. (Keeps your 3 tables, adds `service_history`, adds 2 columns, turns on RLS.)
   Project Settings -> API: copy the project URL and the **service_role** key (backend only!).
2. **Render** (Web Service, repo root as Root Directory):
   - Build command: `pip install -r backend/requirements.txt`
   - Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - Environment: `SUPABASE_URL`, `SUPABASE_KEY`, `API_KEY` (any long random string), `PYTHON_VERSION=3.12.7`
   - Open `https://<service>.onrender.com/health` -> should say `{"status":"ok","database":"connected"}`.
3. **Streamlit Community Cloud**: main file `app.py`. Settings -> Secrets:
   ```
   API_URL = "https://<service>.onrender.com"
   API_KEY = "<same API_KEY as Render>"
   ```

## Run locally
```bash
python -m venv venv && venv\Scripts\activate        # Windows  (source venv/bin/activate on Mac/Linux)
pip install -r requirements-dev.txt
copy .env.example config.env                        # fill in SUPABASE_URL / SUPABASE_KEY / API_KEY
copy .streamlit\secrets.toml.example .streamlit\secrets.toml   # API_URL = "http://127.0.0.1:8001"
# terminal 1 (backend)
uvicorn backend.main:app --reload --port 8001
# terminal 2 (frontend)
streamlit run app.py
# terminal 3 (optional: simulated sensors)
python simulator.py --url http://127.0.0.1:8001 --key <API_KEY> --rounds 5
pytest -q
```
API docs: `/docs`.  Docker: `docker build -t waste-api . && docker run -p 8001:8001 --env-file config.env waste-api`.

## Never commit
`config.env`, `.streamlit/secrets.toml`, `venv/` (all listed in `.gitignore`).
