# CITY HUNT BACKUP: Deploy without Railway

This is a separate version of the original Python multiplayer game, with 9 recce-based missions and team-wide scores. It does **not** include live Railway data, the later iPhone photo-picker patches or current team codes. It starts with a fresh database; do not treat it as a synchronized failover.

## Render deployment (recommended)

1. Connect the Render app in ChatGPT, or use https://dashboard.render.com/ on a desktop.
2. Upload this `city-hunt` directory into a PRIVATE GitHub repository. Do not include real customer data.
3. Select **New > Blueprint** and import the repo (it contains `render.yaml`).
4. Choose a hosting plan that supports a persistent disk. The template uses `starter` (paid). Without persistent storage, team scores and photos may disappear when the instance restarts.
5. Set `ADMIN_PASSWORD` to a NEW unique password of 12+ characters. Do not reuse the short live-game password. Set `PUBLIC_URL` to the actual Render `https://...onrender.com` domain.
6. Deploy; verify `/health` returns OK. Visit `/admin`, review and verify missions, set the team codes and use **Start game**.
7. Share the player URL after an iPhone and Android photo-upload test. Scan the generated QR code for the new Render URL, not the old Railway QR.

## Limitations

- This is an independent backup application, **not** a copy of the current Railway database. No existing teams, player registrations, photos, scores or passwords are transferred.
- Mission descriptions and answers are based on the photos from the gallery recce but require final on-site verification.
- Clue photos are bundled in `recce_photos/` for organisers, but this earlier engine does not display them inline automatically. They can be incorporated in a further UI update.
- New photo uploads must be tested on actual phones before relying on the backup.
- This game uses a single SQLite writer/server. Keep one instance unless the data layer is redesigned.

## Manual local test

`pip install -r requirements.txt` then set `ADMIN_PASSWORD`, `APP_ENV=production`, `DATA_DIR=./data` and run `python run.py`. Open http://localhost:8000 (local only).
