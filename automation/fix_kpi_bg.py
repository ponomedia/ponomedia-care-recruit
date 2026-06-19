#!/usr/bin/env python3
import os

BASE = r"C:\Users\okahara\Desktop\ponomedia 介護採用事業専用\care-recruit-growth\sites"
BG = "linear-gradient(rgba(238,241,247,.92),rgba(238,241,247,.92)),url(imgs/consult.jpg) center/cover no-repeat"

SITES = [
    ("service-lp",      "background:var(--paper-2); border-top",  "background:" + BG + "; border-top"),
    ("service-kensetsu","background:var(--paper-2);border-top",   "background:" + BG + ";border-top"),
    ("service-hoiku",   "background:var(--paper-2);border-top",   "background:" + BG + ";border-top"),
    ("service-inshoku", "background:var(--paper-2);border-top",   "background:" + BG + ";border-top"),
    ("service-butsuryu","background:var(--paper-2);border-top",   "background:" + BG + ";border-top"),
    ("service-seisou",  "background:var(--paper-2);border-top",   "background:" + BG + ";border-top"),
]

for site, old, new in SITES:
    path = os.path.join(BASE, site, "index.html")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if old in content:
        content = content.replace(old, new, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("OK " + site)
    else:
        print("MISS " + site)
