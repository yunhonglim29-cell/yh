"""Build a self-contained, offline demonstration. Never deploy this as the event server."""
from pathlib import Path
import base64
import json
from seed import make_missions

root = Path(__file__).resolve().parent
city = 'data:image/svg+xml;base64,' + base64.b64encode((root/'static/city.svg').read_bytes()).decode()
icon = 'data:image/svg+xml;base64,' + base64.b64encode((root/'static/icon.svg').read_bytes()).decode()
css = (root/'static/styles.css').read_text()
js = (root/'static/app.js').read_text().replace('/static/city.svg', city)
adapter = (root/'demo-adapter.js').read_text()
seed = json.dumps(make_missions(), ensure_ascii=False).replace('<', '\\u003c')
html = f'''<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b1723"><title>CITY HUNT · Interactive demo</title><link rel="icon" href="{icon}"><style>{css}</style></head><body>
<div id="app"><div class="boot"><div class="boot-mark">CH<span>↗</span></div><p>Getting your adventure ready…</p></div></div><div id="toast" role="status" aria-live="polite"></div><div id="modal-root"></div>
<script>window.CITY_DEMO_MISSIONS={seed};</script><script>{adapter}</script><script>{js}</script>
</body></html>'''
output = root/'CITY_HUNT_DEMO.html'
output.write_text(html, encoding='utf-8')
print(output)
