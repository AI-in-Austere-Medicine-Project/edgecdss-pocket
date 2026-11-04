#!/usr/bin/env python3
"""Doses and volumes from EdgeCDSS's own code, for every exported entry.

Run with the EdgeCDSS tree the bank came from:

    python3 tests/fixtures/gen_edgecdss_golden.py \
        --server <edgecdss>/server --kit <drug_concentrations.json> \
        --bank bank/bank.json --out tests/fixtures/edgecdss_golden.json

Calls drug_contracts.resolve_dose and openai_client.resolve_dose_volume, so the
port is compared with the code it was ported from, not with itself.
"""
import argparse
import json
import pathlib
import sys

WEIGHTS = (2.0, 3.0, 5.0, 12.5, 20.0, 39.9, 40.0, 75.0, 79.8, 80.0, 120.0, 150.0, None)

ap = argparse.ArgumentParser()
ap.add_argument("--server", required=True, type=pathlib.Path)
ap.add_argument("--kit", required=True, type=pathlib.Path)
ap.add_argument("--bank", required=True, type=pathlib.Path)
ap.add_argument("--out", required=True, type=pathlib.Path)
args = ap.parse_args()
sys.path.insert(0, str(args.server.resolve()))

import drug_concentrations as cc  # noqa: E402
import drug_contracts as dc  # noqa: E402
import openai_client as oc  # noqa: E402

cc.CONFIG = args.kit.resolve()
cc.ENTRIES, cc.REJECTIONS, cc._RAW = cc._load()

live = {}
for name, entries in dc.servable_entries().items():
    for e in entries:
        live[(name, e["indication"], e["route"], e["population"])] = e

rows = []
for b in json.loads(args.bank.read_text())["entries"]:
    key = (b["drug"], b["indication"], b["route"], b["population"])
    entry = live[key]
    for w in WEIGHTS:
        r = dc.resolve_dose(entry, w)
        row = {"key": list(key), "weight": w, "kind": r["kind"], "dose_mg": r["dose_mg"],
               "display_value": r["display_value"], "display_units": r["display_units"],
               "floor_applied": r["floor_applied"], "range_text": dc.range_text(entry)}
        if r["dose_mg"] is not None:
            d = oc.resolve_dose_volume(oc.DoseCandidate(
                drug=b["drug"], indication=b["indication"], route=b["route"],
                dose_mg=round(r["dose_mg"], 4), source="golden",
                display_value=r["display_value"], display_units=r["display_units"],
                dilution=dc.push_dilution(entry)), oc.PatientContext())
            row.update(volume_ml=d.volume_ml, concentration_mg_ml=d.concentration_mg_ml,
                       diluted=bool(d.dilute_from), refused=bool(d.volume_refusal))
        rows.append(row)
args.out.write_text(json.dumps(rows, indent=0, ensure_ascii=False) + "\n")
print(len(rows), "rows")
