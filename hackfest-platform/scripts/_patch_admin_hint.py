import pathlib

p = pathlib.Path("frontend/admin.html")
s = p.read_text(encoding="utf-8")
old = '            <p class="muted">Switching to closed takes effect immediately. Existing accounts are unaffected.</p>'
new = (
    '            <p class="muted">Switching to closed takes effect immediately. Existing accounts are unaffected.\n'
    '              Participants sign in at <code>/workspace.html</code> with the exact email you paste here —\n'
    '              they pick their own password on first sign-in, so there are no usernames or event IDs to hand out.</p>'
)
assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old, new), encoding="utf-8")
print("patched frontend/admin.html")
