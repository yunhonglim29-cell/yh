# CITY HUNT: delivery test report

Build date: 21 September 2026, Singapore time.

## Executed checks

**Backend automated suite: 37 passing tests.** Python 3.13, FastAPI TestClient, SQLite temporary databases, and the dependency versions in `requirements.txt` were used.

The suite covers:

- All eight rotations, including Team 8 wrapping from 8 to 1.
- Wrong team codes, organiser isolation, missing CSRF and cross-origin requests.
- Only current mission/stage content returned; no answer keys in player stage responses.
- Concurrent same-team photo and answer submissions scoring exactly once.
- Authenticated photo access, cross-team denial, invalid-image rejection and metadata-stripping re-encoding.
- Photo rejection and re-approval adjusting totals without duplicate points.
- Manual review, partial credit limits and progress continuing while review is pending.
- Wrong-answer attempts and repeat request IDs.
- Hint ordering and one-time deductions.
- Bonus idempotency, live score reads and leaderboard lock settings.
- Whole-game and individual-team pause; player-session revocation.
- Mission editor validation, recce readiness gate and reset safeguards.
- Current-mission reset retaining other teams' state and correcting points categories.
- Saved sessions surviving application re-creation with the same data directory.
- Targeted announcement privacy, CSV exports, QR generation and private backups.
- **Eight teams each completing all eight treasures plus the final challenge, with every valid stage reviewed at full marks, producing 370 points per team.**
- Text normalisation, keywords, numeric ranges/tolerance, choice, multiple select, matching and ordering answer engines.

**Browser UI smoke check: passed.** Headless Chromium, at 1440 × 1000 and 390 × 844 viewports, using the actual bundled UI and local demo adapter. Checked joining, mission start, clue, photo-file selection and client compression, text answer, matching answers, manually graded bonus, creative photo, mission completion, organiser sign-in, photo/written reviews, bonus award and mission-editor rendering. Checked for horizontal overflow on the mobile home and editor screens. No JavaScript page errors were observed.

**Two-browser multiplayer integration check: passed.** Two independent browser page sessions were connected to the actual FastAPI application through a Python TestClient transport bridge. Both players joined the same team. A server photo submission unlocked the question, an answer submitted through the UI changed the shared stage and score, and an organiser bonus propagated to both browser states. Both showed the expected score of 30 points. No JavaScript page errors were observed.

Browser tests were run as controlled in-memory page fixtures because direct URL navigation was blocked by the execution environment. The bridge tests the application/UI contract and polling, not public networking, TLS termination or mobile-radio connectivity.

**Syntax checks: passed.** Python compilation of server, seed, launcher and container entrypoint; JavaScript syntax validation of the player/admin UI and demo adapter.

## Re-running tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Optional browser checks:

```sh
python -m pip install -r requirements-browser.txt
python -m playwright install chromium
python tests/browser_smoke.py
python tests/browser_multiplayer.py
```

An existing browser binary can be selected with `CHROMIUM_PATH`. Otherwise Playwright uses its installed Chromium. Browser screenshots and JSON results are written to `test-output/`, which is excluded from source control. The standalone demo must exist in the project folder before the demo test; a copy is included in the delivered ZIP.

## Not yet verified

An actual cloud deployment and Docker image build were not executed. There is no public participant URL attached to this delivery. A fresh online dependency installation could not be exercised in the restricted build environment; local checks used installed versions matching the pinned requirements.

Physical iPhone/Safari and Android/Chrome camera operation, browser-specific HEIC conversion, gallery Wi-Fi/mobile reception, hosting disk limits, restore on the chosen host, and event-scale load remain event-readiness checks. A mobile-sized Chromium test does not establish real iOS or Android compatibility by itself.

The sample gallery missions have not been verified against a recce. Photos are organiser-reviewed, not checked by image-recognition software. This is a tested first version, not an independent security audit or a guarantee of uninterrupted live-event operation.

## Additional production-mode startup check

Fresh production startup was checked with an HTTPS TestClient origin: Secure/HTTP-only session cookies, organiser login with exact-origin validation, empty player lists and zero scores, random team codes, an accepted Railway healthcheck hostname, and rejection of an unrelated Host header all passed. This is an application configuration test, not a deployed TLS or container test.
