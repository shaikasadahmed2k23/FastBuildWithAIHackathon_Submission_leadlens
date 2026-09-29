# Deploying LeadLens (Render + Vercel, free tiers)

The API runs on Render, the UI on Vercel. Deploy the API first, because the UI needs its URL. Dashboard labels change occasionally; if a button is named slightly differently, the setting it controls is the same.

## 0. Push the repository to GitHub

```bash
git remote add origin https://github.com/<you>/leadlens.git
git push -u origin main
```

Make sure `backend/data/answer_cache_seed.json` is committed if you've built it (`python -m app.prewarm --reset --export`). Without it the app works, but the demo questions aren't pre-cached.

## 1. API on Render

1. Go to <https://dashboard.render.com> and sign in with GitHub.
2. Click **New +** (top right), then **Blueprint**.
3. Under **Connect a repository**, pick `leadlens`; grant Render access to it if asked. Click **Connect**.
4. Render reads `render.yaml` and shows one service, **leadlens-api** (Python, Free). Set the variables marked *sync: false*:

   | Key | Value |
   |---|---|
   | `GROQ_API_KEY` | your Groq key |
   | `GEMINI_API_KEY` | your Gemini key (or leave empty) |
   | `CORS_ORIGINS` | `http://localhost:3000` for now; you'll replace it in step 3 |
   | `CORS_ORIGIN_REGEX` | leave empty, or `https://leadlens-.*\.vercel\.app` to allow Vercel preview deployments |

5. Click **Apply** (or **Deploy Blueprint**). The build installs dependencies and seeds the database (about 2–4 minutes).
6. When the service shows **Live**, copy its URL from the top of the service page, e.g. `https://leadlens-api.onrender.com`.
7. Check it: open `https://leadlens-api.onrender.com/health`. You should see `"status": "ok"` and `"data": {"ready": true, "leads": 4992, ...}`. `cache.entries` shows how many pre-computed answers were loaded.

Free Render instances sleep after about 15 minutes without traffic. The first request after that takes about 30 seconds while the UI shows "Waking up server". The free disk is ephemeral, so approvals and imports are lost when the instance restarts or redeploys.

## 2. UI on Vercel

1. Go to <https://vercel.com/new> and sign in with GitHub.
2. Under **Import Git Repository**, click **Import** next to `leadlens`.
3. On **Configure Project**:
   - **Root Directory:** click **Edit**, choose `frontend`, click **Continue**.
   - **Framework Preset:** Next.js (detected automatically).
   - Leave the build and output settings at their defaults.
   - Open **Environment Variables** and add `NEXT_PUBLIC_API_URL` = your Render URL from step 1.6, with no trailing slash.
4. Click **Deploy** (about 1–2 minutes).
5. Copy the production URL Vercel shows, e.g. `https://leadlens.vercel.app`.

`NEXT_PUBLIC_API_URL` is baked in at build time. If you change it later, redeploy: **Deployments** tab → **⋯** on the latest deployment → **Redeploy**.

## 3. Allow the UI to call the API (CORS)

1. In Render, open **leadlens-api**, then **Environment** in the left menu.
2. Edit `CORS_ORIGINS` to your Vercel URL, e.g. `https://leadlens.vercel.app`. Separate several URLs with commas, and don't use a trailing slash.
3. Click **Save Changes**. Render redeploys automatically (about 1–2 minutes).

## 4. Smoke test

1. Open the Vercel URL. After at most about 30 seconds (cold start) you should see the Overview with 4,992 leads.
2. The top bar shows **LLM: Groq** once a question has been answered, or **Rule-based fallback** if the key is missing or out of quota.
3. On **Ask**, click an example question. If the cache seed was deployed, the answer says **cached, 0 tokens**.
4. The **Reset demo data** link in the sidebar restores the clean seed state at any time.

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI says "The API isn't responding" | Check `NEXT_PUBLIC_API_URL` in Vercel (then redeploy) and that `/health` works on Render |
| Browser console shows a CORS error | `CORS_ORIGINS` must exactly match the Vercel URL: scheme, no trailing slash |
| Every answer is "Rule-based fallback" | `GROQ_API_KEY` is missing or over quota; `/health` → `llm_last_call.error` shows the provider's message |
| Render build fails on Python | `PYTHON_VERSION` must be `3.11.9` (set by `render.yaml`) |
