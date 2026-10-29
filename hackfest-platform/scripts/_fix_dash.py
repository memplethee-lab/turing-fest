import pathlib

p = pathlib.Path("scripts/_patch_readme.py")
s = p.read_text(encoding="utf-8")
before = s.count('"  -- see')
s = s.replace('"  -- see', '"  \u2014 see')
p.write_text(s, encoding="utf-8")
print("replaced dashes:", before)
