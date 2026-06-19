#!/usr/bin/env python3
import os

BASE = r"C:\Users\okahara\Desktop\ponomedia 介護採用事業専用\care-recruit-growth\sites"

FIXES = [
    ("sample-kensetsu",
     'background:linear-gradient(135deg,#1a1a2e 0%,#2d3561 60%,#1a1a2e 100%); background-image:url("imgs/hero.jpg"); background-size:cover; background-position:center; background-blend-mode:multiply;',
     'background:linear-gradient(rgba(26,26,46,.72),rgba(26,26,46,.60)),url("imgs/hero.jpg") center/cover no-repeat;'),
    ("sample-hoiku",
     'background:linear-gradient(135deg,#0d2b1a 0%,#1a5032 60%,#0d2b1a 100%); background-image:url("imgs/hero.jpg"); background-size:cover; background-position:center; background-blend-mode:multiply;',
     'background:linear-gradient(rgba(13,43,26,.72),rgba(13,43,26,.60)),url("imgs/hero.jpg") center/cover no-repeat;'),
    ("sample-inshoku",
     'background:linear-gradient(135deg,#2d1a0e 0%,#5c3020 60%,#2d1a0e 100%); background-image:url("imgs/hero.jpg"); background-size:cover; background-position:center; background-blend-mode:multiply;',
     'background:linear-gradient(rgba(45,26,14,.72),rgba(45,26,14,.60)),url("imgs/hero.jpg") center/cover no-repeat;'),
    ("sample-butsuryu",
     'background:linear-gradient(135deg,#0d1f35 0%,#1a3a5c 60%,#0d1f35 100%); background-image:url("imgs/hero.jpg"); background-size:cover; background-position:center; background-blend-mode:multiply;',
     'background:linear-gradient(rgba(13,31,53,.72),rgba(13,31,53,.60)),url("imgs/hero.jpg") center/cover no-repeat;'),
]

TEXT_SHADOW = ".hero h1{text-shadow:0 2px 12px rgba(0,0,0,.45);}"
MARKER = "color:#fff;padding:60px 0 50px;position:relative;overflow:hidden;}"

for site, old, new in FIXES:
    path = os.path.join(BASE, site, "index.html")
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()
    changed = False
    if old in c:
        c = c.replace(old, new, 1)
        changed = True
    if "text-shadow:0 2px 12px" not in c and MARKER in c:
        c = c.replace(MARKER, MARKER + "\n" + TEXT_SHADOW, 1)
        changed = True
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(c)
        print("OK", site)
    else:
        print("SKIP", site)
