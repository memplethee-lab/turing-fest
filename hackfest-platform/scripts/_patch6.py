import io

path = ".env.example"
s = io.open(path, encoding="utf-8").read()
old = "ADMIN_PASSWORD=pick-a-strong-admin-password"
new = (
    "# Bootstraps the first \"admin\" account only; per-admin accounts live in\n"
    "# the DB afterwards and are managed in the admin UI's Admins tab.\n"
    "ADMIN_PASSWORD=pick-a-strong-admin-password"
)
if "Bootstraps the first" in s:
    print("already patched")
else:
    assert old in s
    s = s.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)
