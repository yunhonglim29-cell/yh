# CITY HUNT: THE URA CHALLENGE

A working, mobile-first treasure hunt for eight teams. This package contains the player website, a server-authoritative multiplayer backend, an organiser dashboard, editable rehearsal missions, and automated tests.

**Delivery status:** built and locally tested. It has not been deployed to a public internet address. The nine sample missions are rehearsal content, not verified Singapore City Gallery exhibits. Replace them after recce before the real event.

## Start here

There are two different ways to try this build:

| File / mode | What it does | Important distinction |
|---|---|---|
| `CITY_HUNT_DEMO.html` | An interactive, standalone demonstration with player and organiser screens | Local to one browser. Other teams have fictional example scores. Not multiplayer and not secure against inspecting answers. |
| `run.py` | Starts the actual multiplayer website and backend | All phones use the same hosted server. Answers and future content remain server-side. Team progress is shared. |

Open the HTML demo in a normal desktop browser. Join Team 1 with code `CITY01`. Select **Organiser** to explore the dashboard without a demo password. Photos and progress are kept in browser storage. The yellow banner remains visible to distinguish the demo from the real game. Some file-preview apps do not execute HTML; use a browser rather than an attachment preview. Do not use the demo file for the competition.

## 1. Run the multiplayer build on your computer

Use Python 3.13, which is the runtime used for the local checks. An internet connection is needed for the initial dependency installation.

**Windows:** extract the ZIP, enter the `city-hunt` folder, and double-click `start-local.bat`. Keep its terminal window open.

**macOS / Linux:** open a terminal in the `city-hunt` folder and run:

```sh
sh start-local.sh
```

Alternatively, install and launch manually:

```sh
python3 -m venv .venv
# macOS / Linux:
. .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

Open these addresses on that computer:

```text
Player website:       http://localhost:8000
Organiser dashboard:  http://localhost:8000/admin
Results display:      http://localhost:8000/results
Health endpoint:      http://localhost:8000/health
```

The terminal prints a randomly generated organiser password on the **first run only**. Save it. The dashboard has no shared hard-coded production password. To set or recover the organiser password, set the `ADMIN_PASSWORD` environment variable to a new secret of at least 12 characters, then restart. Existing data is preserved.

Local rehearsal team codes start as `CITY01` through `CITY08`. A **fresh production database generates random team codes** instead. Read and change the codes in **Teams & players**. Never give players the organiser password.

The real server starts in the lobby with zero scores and no fake players. Sign in as organiser and select **Start game**. Players can join before it starts, but cannot start missions until the game is live.

Localhost is only your own computer. It is not the event link for participants on mobile data. For real play, deploy the complete backend on HTTPS as described below.

## 2. What is implemented

### Player experience

- Mobile layouts, large touch controls, city artwork, and bottom navigation.
- Name, team and optional team-code joining. Returning browsers retain their session.
- Eight fixed rotating routes. Team 8 follows 8, 1, 2, 3, 4, 5, 6, 7.
- Current mission only. Start, read clue, explore, submit proof, answer the next stage.
- Camera / photo-library selection, preview, client resizing, upload progress and saved drafts.
- Ten challenge types: text, multiple choice, multiple select, numbers, photo, observation, matching, ordering, puzzle and team-photo challenges.
- Matching uses touch-friendly category selectors. Ordering uses up/down buttons rather than requiring dragging.
- Case/punctuation/spacing-normalised text answers, alternatives, whole-phrase keywords, numeric tolerances/ranges, configurable attempts and manual marking.
- Team score, progress, answer/photo history, achievements, rules, help, final challenge and finish screen.
- Leaderboard with ranks, scores and completed counts. Opponents' missions, routes and submissions are not returned to player clients.
- Gallery restricted to the player's own team and organisers.
- Up to three hints per mission, with delay, confirmation and optional point deductions.
- Live updates by polling every 1.8 seconds while the page is visible, plus refresh on returning to the page. This is near-real-time polling, not a WebSocket connection.
- Typed-answer drafts and photo drafts on the device where submitted. A connection failure requires reconnecting and retrying; this is not a fully offline game.

### Organiser experience

- Password-protected organiser dashboard with a live team monitor.
- Structured mission editor for all eight treasures and the final challenge. Add/remove stages, edit text, change types, points, answers, hint costs and attempts without editing code.
- Photo and written-answer review, partial credit, regrading, comments and favourite photos.
- Manual bonuses or deductions with reasons and a points transaction history.
- Rename teams, change codes, pause individual teams and revoke player access.
- Start, pause, resume and end the game; optional event countdown.
- Skip a broken mission without awarding unearned points, or restart a team's current mission with a reason and an audit trail.
- Leaderboard visibility, manual lock, automatic lock at a chosen completed-mission count and final reveal.
- All-team or targeted announcements; organiser contact details on the Help page.
- Public join QR and team-specific QR generation using the configured public URL. Codes are not embedded in team QRs.
- CSV exports for results, submissions and the points ledger; private backup ZIP with the SQLite database and uploaded photos.
- Projector-style results and favourite-photo highlights.

### Scoring

The supplied rehearsal missions each contain stages worth 10 + 10 + 10 + 5 + 5 = 40 points. Eight treasures total 320, and the final has five 10-point stages. The normal maximum is **370**, before extra bonuses or hint deductions. Editing stage points changes this maximum.

By default, ordinary photo stages award points immediately, provisionally, while creative photos and written bonus answers await manual review. Select **Event settings → Photo points → Award only after organiser review** to hold ordinary photo points as well. Pending submissions still unlock the next stage, so teams do not have to wait for an organiser at every exhibit.

The server validates image files, but **does not recognise exhibits or detect team members in the photograph**. Organisers must review whether the proof satisfies the task. Rejecting a provisionally awarded photo reverses its points. Repeating a review does not award points twice.

There are no speed points. Server timestamps record joins, mission starts, submissions and completions. Equal scores use the earlier full-game completion timestamp; teams that have not completed remain tied at equal scores. Whole-event pause freezes the optional countdown. Individual team pauses and elapsed exports retain wall-clock timing, so settle unusual timing disputes through the organiser rather than treating the tie-breaker as a perfect measure of active play time.

## 3. Replace rehearsal missions after recce

The model, transport, green-space and other sample targets are **illustrative**. No claim is made that these eight distinct exhibits exist in the gallery on the event date. Questions marked REHEARSAL deliberately make testing easy.

Before the real event:

1. Run a rehearsal, then pause/end it and reset the event. This clears progress but retains mission definitions and team settings.
2. In **Mission editor**, replace each of the eight treasure clues, hints, proof instructions and questions using the recce findings. Configure the final challenge too.
3. Set accepted answers and genuinely exhibit-specific questions. Check that matching/ordering item IDs are unique and correct options exactly match their displayed wording.
4. Mark each mission, including the final, **recce verified** after actually checking it.
5. Turn off **Rehearsal mode**, set organiser contact details, choose review mode and leaderboard rules, and save.
6. Recheck the nine mission point totals, distribute separate team codes, and print the hosted join QR.

Mission edits are allowed only while paused or in the lobby and only when no team has started that mission. This protects in-progress scoring. To replace already-played content, reset the rehearsal first; the reset creates a private backup. For an inaccessible exhibit during play, skip the affected team's current mission and document the reason.

The labels "Mission 1" to "Mission 8" in the editor are treasure IDs. The player may see the first treasure in their route labelled as their first discovery. This keeps the journey clear while preserving the requested rotation.

## 4. Publish the event on HTTPS

This build uses **one Python service, one SQLite database and a persistent private uploads directory**. It is not a static-only site. Do not deploy just `static/` or the demo HTML to a static file host and expect shared scores.

The package includes a Dockerfile, a privilege-dropping Docker entrypoint, and Railway configuration. These deployment files are supplied, but an actual cloud deployment was not performed during delivery.

### Required deployment configuration

| Setting | Value |
|---|---|
| Build | Included `Dockerfile` |
| Replicas | **1** |
| Worker processes | **1**, as configured by `run.py` |
| Persistent volume | Mount at `/data` **before entering real event data** |
| `DATA_DIR` | `/data` |
| `APP_ENV` | `production` |
| `ADMIN_PASSWORD` | A unique secret, at least 12 characters, preferably longer |
| `PUBLIC_URL` | The exact HTTPS origin players will open, without a path or trailing query |
| `PORT` | Use the hosting provider's assigned `PORT`; `run.py` reads it |
| Health check | `/health` |

`PUBLIC_URL` example:

```text
https://your-actual-game-domain.example
```

Replace the example with the real address. This setting must exactly match the browser origin for CSRF checks and QR generation. Redirect other hostnames to that address. HTTPS is terminated by the host's reverse proxy, not by the Python process.

### Railway path

Upload this folder's **source code** to a private repository and deploy it as one service using the included Dockerfile. Attach a volume at `/data`. Set the variables above, generate the service's public domain under Networking, then set `PUBLIC_URL` to that HTTPS origin and redeploy. If the first startup fails because the public URL has not yet been configured, add the domain and variable and redeploy; do not disable the production check.

Railway volumes are mounted at runtime, not during the image build. The included entrypoint prepares the volume permissions at runtime, then runs the application as UID/GID 10001. Keep the container's default entrypoint rather than overriding it with `python run.py` when using the Dockerfile. Railway's healthcheck hostname is allowed by the application.

Once the site is live, open `/admin`, confirm the team codes, configure the event, and use **Share & exports** to obtain the real join link and QR. Scan it using phones on mobile data, not only the organiser's Wi-Fi.

The same container can run on another persistent-volume HTTPS host. Never increase the number of replicas with this SQLite architecture. Replacing it with a distributed database and object storage would be a separate deployment design.

Useful official deployment references, checked for this build:

```text
Railway volumes:      https://docs.railway.com/volumes
Railway healthchecks: https://docs.railway.com/deployments/healthchecks
Railway deployments:  https://docs.railway.com/build-deploy
```

### Reverse-proxy configuration

Keep direct public access to the Python port blocked. If your host requires forwarded client/protocol headers, set `FORWARDED_ALLOW_IPS` to the known proxy addresses. Use `*` only when **all** incoming traffic is forced through a trusted provider proxy and direct access is impossible. Otherwise a caller could spoof forwarding headers, including those used for rate limiting.

The default trusts only localhost. With an untrusted external proxy, login rate limits can group players under the proxy's IP. Test the chosen host and adjust proxy trust deliberately before the event. Do not advertise a temporary HTTP development deployment as the real event link.

## 5. Data, backups and privacy

All real event state lives under `DATA_DIR`:

```text
data/
  city-hunt.sqlite3
  city-hunt.sqlite3-wal    # present while SQLite WAL is active
  city-hunt.sqlite3-shm
  .session-secret
  uploads/                # private re-encoded JPEG files
  backups/                # private snapshot ZIP files
```

The browser never receives database credentials or administrator answer keys. Team-code hashes and an organiser password hash are stored server-side. Clear team codes are also retained in the private team settings to support organiser distribution. Therefore database backups are sensitive even though passwords are hashed.

Production sessions use signed, HTTP-only, Secure, SameSite cookies and CSRF verification. The player session lasts up to 14 days; organiser access expires after eight hours. Do not use the organiser session on a device handed to players. This is a single organiser credential with a generic organiser audit identity, not a named, multi-admin account system.

Photos are resized and re-encoded as JPEG on the server, removing EXIF metadata. Valid JPEG, PNG and WebP input is accepted. The client attempts to convert camera images to JPEG; HEIC decoding depends on the browser. When an image cannot be read, retake it or select a JPEG/PNG. No automated face or location recognition is performed.

Ask people before photographing them. Avoid other gallery visitors. Tell participants who can access photos and how long they will be retained. Put event-specific instructions in the Help contact field. The join checkbox is a reminder, not a substitute for the organiser's own consent process.

**Reset is not permanent erasure.** Resets hide/clear active game records and create a backup first. Old files may remain in private uploads and backups. Export only what you need, keep backups private, and delete all retained copies according to your retention policy. Browser photo drafts and exported copies also need separate consideration.

For a complete purge after the event, stop the service, remove the event's dedicated `DATA_DIR` and its off-server backup/export copies, then start with a fresh directory when needed. This also discards sessions and event configuration. Preserve a clean, non-personal mission configuration separately if reusing the hunt.

To restore a backup: stop the service; copy the current data directory somewhere secure; extract the snapshot database and uploads into `DATA_DIR`; remove stale `-wal` and `-shm` files only while stopped; retain the existing `.session-secret`; restart. The snapshot includes restore instructions. Do not edit a running SQLite database by hand. Keep automatic redeployments off during live play because a volume-backed restart can interrupt service.

## 6. Event-day checks

Use at least one actual iPhone running Safari and one Android phone running Chrome. Test two teammates on separate devices, camera capture, photo-library upload, page closing/reopening, a wrong answer and retry, a paid hint, organiser approval, score updates and the final QR.

Rehearse from the gallery using the intended mobile connections. Do not assume indoor reception. Test your full expected group, including uploads and a restart, on the selected hosting plan. Have organiser instructions for connection problems and inaccessible exhibits. Browser camera behaviour and real gallery connectivity were not physically verified in this delivery.

Before distributing the event link: ensure all scores are zero, test players removed, real team codes set, all nine missions recce-verified, rehearsal mode off, and the game in the lobby. Start together from the dashboard. At the end, stop submissions, complete pending reviews, export results, then reveal final rankings.

## 7. Tests and implementation notes

Run the backend suite:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The delivered suite tests rotating routes, all challenge engines, answer-key isolation, auth/CSRF, duplicate submissions under concurrency, cross-team photo access, manual grading, hint costs, bonuses, pauses, resets, exports, backups, the final challenge and complete 370-point runs for all eight teams.

See `TEST_REPORT.md` for the actual executed checks, browser test scope and remaining limitations. Frontend assets have no build step and no CDN dependencies. SQLite uses transactions and unique action keys; point changes are represented by a ledger rather than trusting a browser-supplied total.

### Deliberate v1 boundaries

This is one active event with eight teams and a final mission. Event resets support reuse, but there is no multi-event account portal. It includes matching, ordering and puzzle activities, not bespoke skyline-image puzzles, memory-card arcade games or a gacha system. Announcements are in-app, not push notifications, SMS or email. There is no AI photo recognition, SSO, per-organiser roles, background offline upload, or cloud deployment already attached.

## File map

```text
app.py                 API, transactions, permissions, uploads, reviews and exports
seed.py                Editable rehearsal mission templates, never served to players
run.py                 Start the real event server
static/app.js          Player and organiser interface
static/styles.css      Responsive layouts and theme
static/city.svg        Original decorative city artwork, not an exhibit map
static/index.html      Server-delivered web entry point
CITY_HUNT_DEMO.html    Standalone local-only demonstration
build_demo.py          Rebuild the HTML demo from source
Dockerfile             Container build for a persistent-volume host
railway.json           Single-service deployment settings
start-local.*          Windows and macOS/Linux local launch helpers
tests/                 Backend tests
TEST_REPORT.md         Delivery verification and remaining checks
```

This is an organiser-created game, not an official URA application. No live participant data, event admin password or private photographs are included in the package.
