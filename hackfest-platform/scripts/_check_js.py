"""Extract inline <script> bodies so `node --check` can validate them."""
import pathlib
import re

for rel in ["frontend/index.html", "frontend/workspace.html", "frontend/admin.html"]:
    html = pathlib.Path(rel).read_text(encoding="utf-8")
    # only inline scripts (skip ones with a src= attribute)
    bodies = [
        m.group(1)
        for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    ]
    out = pathlib.Path("scripts") / ("_js_" + pathlib.Path(rel).stem + ".js")
    out.write_text("\n".join(bodies), encoding="utf-8")
    print(out, len(bodies), "inline script block(s)")
