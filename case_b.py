#!/usr/bin/env python3
"""CLI implementasi Case B. Semua invocation dicatat pada output/<run_id>."""
import argparse
import contextlib
import io
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from caseb.runlog import Run, write_json

BASE = Path(__file__).resolve().parent


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def parser():
    p = Parser(description=__doc__, epilog="Global: --output-root DIR dan --config FILE boleh diletakkan sebelum/sesudah subcommand.")
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)
    sub.add_parser("doctor", help="Periksa dependensi, CLI HackRF dan perangkat (read-only)")
    sub.add_parser("plan", help="Buat jadwal 33 trial serta template metadata/log")
    demo = sub.add_parser("demo", help="Uji IQ sintetis + 33 trial CSI + LOSO, tanpa radio")
    demo.add_argument("--seed", type=int, default=7)
    sub.add_parser("selftest", help="Uji numerik, gap, anti-kebocoran, dan logging")
    r = sub.add_parser("record", help="Capture RX-only lalu ekstrak CSI otomatis")
    r.add_argument("--duration", type=float, default=60)
    r.add_argument("--metadata", type=Path, required=True)
    e = sub.add_parser("extract", help="Ekstrak CSI dari .cs8 yang sudah ada")
    e.add_argument("iq", type=Path)
    e.add_argument("--metadata", type=Path, required=True)
    a = sub.add_parser("analyze", help="Pra-proses dan FFT satu trial; carrier tetap atau model fold latih")
    a.add_argument("csi", type=Path)
    a.add_argument("--metadata", type=Path, required=True)
    a.add_argument("--model", type=Path, help="JSON {selected_k:[...]} hasil fold latih; default fixed k=1")
    v = sub.add_parser("evaluate", help="Evaluasi dataset CSV dengan LOSO/leave-one-person-out")
    v.add_argument("dataset", type=Path)
    v.add_argument("--split", choices=["session", "person"], default="session")
    return p


def validate_config(cfg):
    import math
    from caseb.radio import K
    for value in cfg.values():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Konfigurasi harus finite")
    if cfg["fs_hz"] != 20_000_000:
        raise ValueError("Ekstraktor LTF ini khusus 20 Msps, FFT 64")
    if cfg["lna_db"] not in range(0, 41, 8) or cfg["vga_db"] not in range(0, 63, 2):
        raise ValueError("LNA 0..40 langkah 8; VGA 0..62 langkah 2")
    if cfg["amplifier"] not in (0, 1):
        raise ValueError("amplifier harus 0 atau 1")
    channel = cfg["channel"]
    expected = (2484 if channel == 14 else 2407+5*channel if 1 <= channel <= 13 else 5000+5*channel)*1_000_000
    if cfg["center_freq_hz"] != expected or not 1 <= channel <= 177:
        raise ValueError("channel dan center_freq_hz primary 20 MHz tidak cocok")
    if not 0 < cfg["rho_min"] < 1 or cfg["chunk_samples"] < 640:
        raise ValueError("rho_min harus (0,1), chunk_samples >=640")
    if not 0 <= cfg["clip_fraction_max"] <= 1 or not 0 <= cfg["confidence_min"] <= 1:
        raise ValueError("clip_fraction_max/confidence_min harus 0..1")
    for key in ("min_packet_rate", "pilot_min_packets", "energy_threshold_db", "min_burst_us",
                "resample_hz", "max_gap_s", "window_s", "hop_s", "filter_order"):
        if cfg[key] <= 0:
            raise ValueError(f"{key} harus positif")
    lo, hi = cfg["bandpass_hz"]
    a, b = cfg["search_band_hz"]
    if not 0 < lo <= a < b <= hi < cfg["resample_hz"]/2:
        raise ValueError("Band-pass/search band harus cocok dan di bawah Nyquist")
    if cfg["fixed_subcarrier"] not in K or not 1 <= cfg["aggregate_count"] <= 52:
        raise ValueError("Indeks/jumlah subcarrier tidak valid")
    for key in ("cfo_range_hz", "rssi_range_dbfs"):
        gate = cfg[key]
        if gate is not None and (len(gate) != 2 or not gate[0] < gate[1]):
            raise ValueError(f"{key} harus null atau [min,max]")


def load_meta(path, run):
    run.input(path)
    m = json.loads(path.read_text(encoding="utf-8-sig"))
    for key in ("session_id", "subject_id", "scenario", "duration_s"):
        if key not in m:
            raise ValueError(f"Metadata wajib: {key}")
    import math
    if not math.isfinite(float(m["duration_s"])) or float(m["duration_s"]) <= 0:
        raise ValueError("duration_s harus positif dan finite")
    if m["scenario"] not in ("breathing", "empty", "breath_hold", "pilot"):
        raise ValueError("scenario: breathing/empty/breath_hold/pilot; eksplorasi orientasi tetap breathing")
    if m.get("actual_breath_count") is not None:
        count = float(m["actual_breath_count"])
        if not math.isfinite(count) or count < 0:
            raise ValueError("actual_breath_count harus nonnegatif dan finite")
    if m.get("tx_verified") is True and not m.get("tx_verification_note"):
        raise ValueError("tx_verified perlu tx_verification_note yang menjelaskan bukti pemisahan")
    return m


def load_dataset(path, cfg, run):
    import pandas as pd
    from caseb.analysis import load_trial
    run.input(path)
    manifest = pd.read_csv(path, dtype=str)
    if set(("trial_id", "csi_path", "metadata_path")) - set(manifest):
        raise ValueError("dataset perlu trial_id,csi_path,metadata_path")
    if manifest.trial_id.duplicated().any():
        raise ValueError("trial_id harus unik")
    seen = set()
    trials = []
    for row in manifest.itertuples(index=False):
        if Path(row.trial_id).name != row.trial_id or row.trial_id in (".", ".."):
            raise ValueError("trial_id harus nama direktori sederhana")
        csi = (path.parent/row.csi_path).resolve()
        meta = load_meta((path.parent/row.metadata_path).resolve(), run)
        run.input(csi)
        digest = run.manifest["inputs"][-1]["sha256"]
        if digest in seen:
            raise ValueError("CSI identik dipakai lebih dari sekali; potensi kebocoran trial")
        seen.add(digest)
        if meta.get("trial_id", row.trial_id) != row.trial_id:
            raise ValueError("trial_id dataset dan metadata tidak cocok")
        meta["trial_id"] = row.trial_id
        for col in ("session_id", "subject_id"):
            if col not in meta or str(meta[col]) in ("unknown", "", "nan"):
                raise ValueError(f"Metadata evaluasi wajib memiliki {col} yang nyata")
        trials.append(load_trial(csi, meta, cfg))
    kinds = {t["meta"].get("synthetic") is True for t in trials}
    if len(kinds) > 1:
        raise ValueError("Pisahkan dataset sintetis dari eksperimen nyata")
    hardware = ("fs_hz", "center_freq_hz", "lna_db", "vga_db", "amplifier")
    recorded = {tuple(t["meta"]["radio_config"][k] for k in hardware)
                for t in trials if "radio_config" in t["meta"]}
    if len(recorded) > 1:
        raise ValueError("Konfigurasi radio/gain berbeda antartrial; pisahkan eksperimen pembanding")
    if recorded and next(iter(recorded)) != tuple(cfg[k] for k in hardware):
        raise ValueError("Konfigurasi analisis berbeda dari radio_config rekaman")
    return trials


def session_log(out, meta, cfg, qc):
    import pandas as pd
    fields = ["session_id", "subject_id", "scenario", "target_bpm", "actual_breath_count", "duration_s",
              "date_time", "room", "channel", "center_freq_hz", "fs_hz", "lna_db", "vga_db", "amplifier",
              "tx_device", "rx_position", "subject_position", "orientation", "observed_motion", "valid_packet_rate",
              "max_gap_s", "clipping_status", "note", "tx_verified", "tx_verification_note"]
    values = {**meta, **cfg, **qc}
    pd.DataFrame([{k: values.get(k, "") for k in fields}]).to_csv(out/"log_sesi.csv", index=False)


def execute(args, cfg, run):
    import numpy as np
    import pandas as pd
    from caseb import analysis, radio, synthetic
    if args.command == "doctor":
        checks = {"dependencies": run.manifest["versions"], "device": "not_checked"}
        for name in ("hackrf_transfer", "hackrf_info"):
            checks[name] = shutil.which(name)
        if checks["hackrf_info"]:
            r = subprocess.run(["hackrf_info"], capture_output=True, text=True, timeout=15)
            (run.path/"hackrf_info.txt").write_text(r.stdout+r.stderr, encoding="utf-8")
            checks["device"] = "available" if r.returncode == 0 else "unavailable"
        write_json(run.path/"doctor.json", checks)
        print(json.dumps(checks, indent=2))
    elif args.command == "plan":
        entries = []
        for s in ("S1", "S2", "S3"):
            entries.append(dict(session_id=s, subject_id="none", scenario="empty", target_bpm=None, duration_s=60))
            for p in ("P1", "P2", "P3"):
                for bpm in (10, 15, 20):
                    entries.append(dict(session_id=s, subject_id=p, scenario="breathing", target_bpm=bpm, duration_s=60))
        for p in ("P1", "P2", "P3"):
            entries.append(dict(session_id="S1", subject_id=p, scenario="breath_hold", target_bpm=None, duration_s=15))
        df = pd.DataFrame(entries)
        df.insert(0, "trial_id", [f"B_{i+1:02d}_{r.session_id}_{r.subject_id}_{r.scenario}" for i, r in df.iterrows()])
        df["actual_breath_count"] = ""
        df["note"] = ""
        df.to_csv(run.path/"jadwal_protokol.csv", index=False)
        shutil.copy(BASE/"config/metadata.example.json", run.path/"metadata.example.json")
        session_log(run.path, {}, cfg, {})
    elif args.command in ("record", "extract"):
        meta = load_meta(args.metadata, run)
        meta.setdefault("date_time", datetime.now(timezone.utc).isoformat())
        if args.command == "record":
            if not np.isfinite(args.duration) or args.duration <= 0:
                raise ValueError("--duration harus positif dan finite")
            if abs(float(meta["duration_s"])-args.duration) > 1e-6:
                raise ValueError("--duration harus sesuai metadata.duration_s")
            qc = radio.record(run, cfg, meta, args.duration)
        else:
            run.input(args.iq)
            actual = args.iq.stat().st_size/(2*cfg["fs_hz"])
            if abs(actual-float(meta["duration_s"])) > 1/cfg["fs_hz"]:
                raise ValueError("Ukuran IQ tidak sesuai duration_s metadata; jangan ganti durasi untuk menutupi capture parsial")
            qc = radio.extract(args.iq, run.path, cfg, meta, run.log)
        session_log(run.path, {**meta, "duration_s": qc["duration_s"]}, cfg, qc)
        print(json.dumps(qc, indent=2))
        if not qc["pilot_pass"]:
            run.log.warning("QC gagal; artefak disimpan, perbaiki kualitas sebelum interpretasi")
            return "qc_failed", 2
    elif args.command == "analyze":
        meta = load_meta(args.metadata, run)
        run.input(args.csi)
        selected = [int(np.flatnonzero(radio.K == cfg["fixed_subcarrier"])[0])]
        if args.model:
            run.input(args.model)
            model = json.loads(args.model.read_text(encoding="utf-8-sig"))
            ks = model["selected_k"]
            if not ks or any(k not in radio.K for k in ks):
                raise ValueError("model.selected_k tidak valid")
            selected = [int(np.flatnonzero(radio.K == k)[0]) for k in ks]
        write_json(run.path/"model_used.json", {"selected_k": radio.K[selected].tolist(),
                                               "source": str(args.model) if args.model else "fixed baseline; no test selection"})
        trial = analysis.load_trial(args.csi, meta, cfg)
        analysis.save_analysis(trial, run.path, selected, cfg)
    elif args.command == "evaluate":
        trials = load_dataset(args.dataset.resolve(), cfg, run)
        analysis.evaluate(trials, run.path, cfg, "session_id" if args.split == "session" else "subject_id")
    elif args.command == "demo":
        write_json(run.path/"SYNTHETIC.json", {"seed": args.seed, "warning": "DATA SINTETIS; bukan hasil riset nyata"})
        raw = run.path/"synthetic_pilot.cs8"
        truth = synthetic.make_iq(raw, seed=args.seed)
        write_json(run.path/"iq_truth.json", truth)
        qc = radio.extract(raw, run.path, cfg, {"session_id": "SYNTH", "subject_id": "none",
                           "scenario": "pilot", "synthetic": True}, run.log)
        csi = pd.read_csv(run.path/"csi.csv")
        if not qc["pilot_pass"]:
            raise AssertionError("Synthetic IQ extraction QC failed")
        relative_error = float(np.median(abs(csi[radio.AMP].to_numpy()-truth["amplitude"])/truth["amplitude"]))
        cfo_error = float(abs(csi.cfo_hz.median()-truth["cfo_hz"]))
        write_json(run.path/"iq_verification.json", {"median_relative_amplitude_error": relative_error,
                                                     "cfo_error_hz": cfo_error})
        if relative_error > .05 or cfo_error > 3000:
            raise AssertionError("Synthetic IQ numerical verification failed")
        dataset = synthetic.make_dataset(run.path/"synthetic_dataset", args.seed)
        trials = load_dataset(dataset, cfg, run)
        result = run.path/"evaluation"
        result.mkdir()
        analysis.evaluate(trials, result, cfg)
        # Demonstrate short control energy without forcing 30 s FFT predictions.
        control = next(t for t in trials if t["meta"]["scenario"] == "breath_hold")
        ctrlout = run.path/"short_control"
        ctrlout.mkdir()
        analysis.save_analysis(control, ctrlout, [int(np.flatnonzero(radio.K == 1)[0])], cfg)
        print("Demo sintetis selesai; lihat evaluation/ dan iq_verification.json")
    elif args.command == "selftest":
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(BASE/"tests"), "-v"],
                                capture_output=True, text=True, cwd=BASE)
        (run.path/"tests.txt").write_text(result.stdout+result.stderr, encoding="utf-8")
        print(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError("Selftest gagal; lihat tests.txt")
    return "completed", 0


def main():
    # Bootstrap before parsing so help, bad arguments, and failures are archived too.
    boot = argparse.ArgumentParser(add_help=False)
    boot.add_argument("--output-root", default="output")
    boot.add_argument("--config", type=Path, default=BASE/"config/default.json")
    # Defer malformed bootstrap arguments to the logged main parser.
    try:
        opt, remaining = boot.parse_known_args()
    except SystemExit:
        opt, remaining = boot.parse_args([]), sys.argv[1:]
    command = next((s for s in remaining if s in ("doctor", "plan", "demo", "record", "extract", "analyze", "evaluate", "selftest")), "cli")
    run = Run(opt.output_root, command, {"raw_argv": sys.argv[1:]})
    status, code = "completed", 0
    try:
        capture = io.StringIO()
        try:
            with contextlib.redirect_stdout(capture):
                args = parser().parse_args(remaining)
        finally:
            if capture.getvalue():
                (run.path/"cli_output.txt").write_text(capture.getvalue(), encoding="utf-8")
                print(capture.getvalue(), end="")
        run.manifest["arguments"] = vars(args)
        run.input(opt.config)
        cfg = json.loads(opt.config.read_text(encoding="utf-8-sig"))
        validate_config(cfg)
        write_json(run.path/"config.json", cfg)
        status, code = execute(args, cfg, run)
    except SystemExit as exc:
        code = int(exc.code or 0)
        status = "completed" if code == 0 else "failed"
    except KeyboardInterrupt:
        status, code = "interrupted", 130
        run.failure()
    except Exception as exc:
        status, code = "failed", 1
        run.failure()
        run.manifest["error"] = str(exc)
        print(f"ERROR: {exc}\nDetail: {run.path/'error.txt'}", file=sys.stderr)
    finally:
        run.finish(status)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
