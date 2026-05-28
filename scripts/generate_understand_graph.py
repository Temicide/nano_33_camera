#!/usr/bin/env python3
import ast
import html
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / ".understand-anything"
GRAPH_PATH = OUT_DIR / "knowledge-graph.json"
DASHBOARD_PATH = OUT_DIR / "dashboard.html"
META_PATH = OUT_DIR / "meta.json"

BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".zip", ".pdf"}
SOURCE_SUFFIXES = {
    ".ino",
    ".py",
    ".sh",
    ".html",
    ".md",
    ".csv",
    ".tour",
    ".yaml",
    ".yml",
    ".json",
}

CPP_FUNCTION_RE = re.compile(
    r"(?m)^(?:[A-Za-z_][\w:<>,&*\s]+\s+)([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{"
)
SHELL_FUNCTION_RE = re.compile(r"(?m)^([A-Za-z_]\w*)\s*\(\)\s*\{")
INCLUDE_RE = re.compile(r"^\s*#include\s+[<\"]([^>\"]+)[>\"]", re.MULTILINE)
SCRIPT_REF_RE = re.compile(r"scripts/[A-Za-z0-9_./-]+")


def run_git_ls_files():
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        return [Path(line) for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return [path.relative_to(ROOT) for path in ROOT.rglob("*") if path.is_file()]


def read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def language_for(path):
    suffix = path.suffix.lower()
    if suffix == ".ino":
        return "Arduino C++"
    if suffix == ".py":
        return "Python"
    if suffix == ".sh":
        return "Bash"
    if suffix == ".html":
        return "HTML"
    if suffix == ".md":
        return "Markdown"
    if suffix == ".csv":
        return "CSV"
    if suffix in {".yaml", ".yml"}:
        return "YAML"
    if suffix == ".json":
        return "JSON"
    if suffix == ".tour":
        return "CodeTour"
    return "Text"


def node_type_for(path):
    rel = str(path)
    if path.suffix in {".md", ".tour"} or rel.startswith("docs/"):
        return "document"
    if path.suffix in {".json", ".yaml", ".yml"} or path.name in {
        "AGENTS.md",
        "CLAUDE.md",
        "skills-lock.json",
    }:
        return "config" if not rel.startswith("docs/training_data/") else "document"
    if path.suffix == ".html":
        return "file"
    if path.suffix == ".csv":
        return "document"
    return "file"


def file_category_for(path):
    rel = str(path)
    if rel.startswith("docs/training_data/") or rel.startswith("data/"):
        return "data"
    if path.suffix in {".md", ".tour"} or rel.startswith("docs/"):
        return "docs"
    if path.suffix in {".json", ".yaml", ".yml"}:
        return "config"
    if path.suffix == ".sh":
        return "script"
    if path.suffix == ".html":
        return "markup"
    return "code"


def layer_for(path):
    text = str(path)
    if path.suffix == ".html" or path.name in {"detect_web.py", "data_collector.py", "detect_data_collector.py"}:
        return "ui"
    if text.startswith("docs/training_data") or text.startswith("data/"):
        return "data"
    if path.suffix == ".md" or text.startswith("docs/") or text.startswith("tours/"):
        return "data"
    if path.name in {"upload.sh", "port.sh", "monitor.sh", "ei_deploy.sh", "ei_connect.sh"}:
        return "utility"
    if text.startswith("scripts/"):
        return "service"
    if text.startswith("nano_33/"):
        return "api"
    return "utility"


def file_summary(path, text):
    name = path.name
    rel = str(path)
    if rel == "nano_33/nano_33.ino":
        return (
            "Main firmware sketch. Initializes the Nano 33 BLE, OV7675 camera, "
            "watchdog, exposure presets, Edge Impulse FOMO preprocessing, serial "
            "commands, raw frame streaming, detection streaming, and JSON counts."
        )
    summaries = {
        "upload.sh": "Compiles the Arduino sketch with static Edge Impulse allocation, gates dynamic RAM use, detects the serial port, and uploads to the Nano 33 BLE.",
        "port.sh": "Finds the likely Nano 33 serial port for upload, monitoring, and viewer scripts.",
        "monitor.sh": "Opens a serial monitor against the detected or configured Nano 33 port.",
        "live_view.sh": "Shell entrypoint for the OpenCV raw camera viewer.",
        "live_detect.sh": "Shell entrypoint for the OpenCV detection-stream viewer.",
        "detect_web.sh": "Shell entrypoint for the Flask browser detection viewer.",
        "collect.sh": "Shell entrypoint for the browser raw-frame training data collector.",
        "collect_detect.sh": "Shell entrypoint for the detection-assisted data collector.",
        "ei_deploy.sh": "Installs an Edge Impulse Arduino or C++ export as the pill_counting_inferencing library and validates model dimensions and arena size.",
        "ei_connect.sh": "Connects the attached board to Edge Impulse tooling.",
        "live_camera_view.py": "OpenCV viewer for raw grayscale OVF1 frames streamed by the firmware.",
        "live_detect_view.py": "OpenCV viewer for OVD1 detection frames, bounding boxes, count, FPS, and exposure keyboard controls.",
        "detect_web.py": "Flask app that reads OVD1 packets in a background serial thread and serves an MJPEG detection dashboard.",
        "data_collector.py": "Flask app that reads OVF1 raw frames, serves an MJPEG preview, and captures grayscale PNG training images.",
        "detect_data_collector.py": "Detection-assisted Flask collector that combines live detections with training capture metadata.",
        "calibrate_wb.py": "White-balance and exposure calibration helper for camera tuning.",
        "test_training_data.py": "Builds a local Edge Impulse runner, preprocesses captured training PNGs like the firmware, and writes detection-count CSV results.",
        "README.md": "Project overview, hardware assumptions, setup, build/upload commands, serial protocol, model checks, and troubleshooting notes.",
        "AGENTS.md": "Repository operating instructions for structure, coding style, testing, PRs, and generated-file hygiene.",
        "CLAUDE.md": "Local assistant-facing project notes and command reminders.",
        "model_and_ram.md": "Notes about model size, RAM constraints, and deployment tradeoffs.",
        "index.html": "Browser template for raw-frame data collection.",
        "detect.html": "Browser template for live detection viewing and exposure controls.",
        "collect_detect.html": "Browser template for detection-assisted capture workflows.",
    }
    if name in summaries:
        return summaries[name]
    if rel.startswith("docs/research/"):
        return "Research note documenting experiments, findings, design decisions, or optimization analysis for the medicine-counting pipeline."
    if rel.startswith("docs/training_data/") and path.suffix == ".json":
        return "Training-data annotation metadata paired with a captured blister image."
    if rel.startswith("data/"):
        return "Structured analysis data used by reports or optimization notes."
    if rel.startswith("tours/"):
        return "CodeTour walkthrough for onboarding through the repository."
    first_heading = next(
        (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")),
        "",
    )
    if first_heading:
        return f"Documentation page: {first_heading}."
    return f"{language_for(path)} file in the {layer_for(path)} layer."


def function_summary(file_path, name):
    rel = str(file_path)
    special = {
        "setup": "Arduino setup entrypoint that initializes serial, shield pins, watchdog, camera geometry, inference mapping, exposure, warmup, and ready status.",
        "loop": "Arduino main loop that dispatches serial commands and runs counting, detection streaming, raw streaming, or idle behavior.",
        "handleSerialCommands": "Reads single-character serial commands and switches firmware modes or camera exposure presets.",
        "doJsonCount": "Captures one frame, runs inference, and emits production-style JSON with count, boxes, and timing.",
        "doDetectionFrame": "Captures a frame, runs inference, writes an OVD1 binary packet with boxes and grayscale bytes, and increments the frame counter.",
        "ei_get_frame_data": "Edge Impulse signal callback that center-crops/downsamples 160x120 grayscale camera data to the 96x96 model input.",
        "runInference": "Wraps Edge Impulse run_classifier for the current camera frame signal.",
        "mapDetectionBoxToFrame": "Maps model-space detection boxes back to full camera-frame coordinates.",
        "printMemoryStatus": "Prints firmware, model, arena, and heap diagnostics over serial.",
        "find_nano_port": "Autodetects the Nano 33 serial device by USB description or usbmodem path.",
        "scan_magic": "Scans the serial byte stream until the expected frame-packet magic marker is found.",
        "read_packet": "Reads and validates one binary frame packet from serial.",
        "decode_frame": "Converts grayscale packet bytes into an OpenCV BGR frame.",
        "draw_overlay": "Draws detection boxes, confidence labels, count, FPS, or frame metadata on an OpenCV frame.",
        "serial_reader": "Background serial loop that waits for the board, starts streaming, parses packets, and updates shared viewer state.",
        "mjpeg_stream": "Yields latest JPEG frames as a multipart MJPEG HTTP response.",
        "generate_mjpeg": "Yields latest JPEG frames as a multipart MJPEG HTTP response.",
        "capture": "Saves the current grayscale frame to docs/training_data using the blister_0001.png naming convention.",
        "build_runner": "Compiles a local C++ Edge Impulse classifier runner for validating captured training data.",
        "preprocess": "Replicates firmware image crop, resize, grayscale packing, and feature formatting for local model checks.",
        "validate_model": "Checks Edge Impulse export metadata against firmware input and RAM constraints.",
        "install_cpp_export": "Stages a C++ MCU Edge Impulse export as an Arduino-compatible library.",
        "install_arduino_export": "Stages an Arduino Edge Impulse export and normalizes library metadata for this project.",
    }
    if name in special:
        return special[name]
    if rel.endswith(".py"):
        return f"Python function `{name}` used by {file_path.name}."
    if rel.endswith(".sh"):
        return f"Bash helper `{name}` used inside {file_path.name}."
    if rel.endswith(".ino"):
        return f"Firmware helper `{name}` in the Nano 33 sketch."
    return f"Function `{name}` declared in {file_path.name}."


def node_id(kind, name):
    safe = re.sub(r"[^A-Za-z0-9_.:/-]+", "_", name)
    return f"{kind}:{safe}"


def add_node(nodes, node):
    if node["id"] not in nodes:
        nodes[node["id"]] = node


def add_edge(edges, source, target, edge_type, label=None):
    if source == target:
        return
    edge_id = node_id("edge", f"{source}->{target}:{edge_type}:{label or ''}")
    edges[edge_id] = {
        "id": edge_id,
        "source": source,
        "target": target,
        "type": edge_type,
        "weight": edge_weight(edge_type),
        **({"label": label} if label else {}),
    }


def edge_weight(edge_type):
    weights = {
        "contains": 1.0,
        "inherits": 0.9,
        "implements": 0.9,
        "calls": 0.8,
        "exports": 0.8,
        "defines_schema": 0.8,
        "imports": 0.7,
        "deploys": 0.7,
        "migrates": 0.7,
        "depends_on": 0.6,
        "configures": 0.6,
        "triggers": 0.6,
        "tested_by": 0.5,
        "documents": 0.5,
        "provisions": 0.5,
        "serves": 0.5,
        "routes": 0.5,
    }
    return weights.get(edge_type, 0.5)


def git_commit_hash():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def extract_python_functions(path, text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    found = []
    for item in ast.walk(tree):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(item, "end_lineno", item.lineno)
            code = "\n".join(lines[item.lineno - 1 : end])
            found.append((item.name, "class" if isinstance(item, ast.ClassDef) else "function", code))
    return sorted(found, key=lambda item: text.find(item[2]))


def extract_cpp_functions(text):
    names = []
    seen = set()
    for match in CPP_FUNCTION_RE.finditer(text):
        name = match.group(1)
        if name in {"if", "while", "for", "switch"} or name in seen:
            continue
        seen.add(name)
        start = match.start()
        next_match = CPP_FUNCTION_RE.search(text, match.end())
        end = next_match.start() if next_match else min(len(text), match.end() + 1800)
        names.append((name, "function", text[start:end].strip()))
    struct_match = re.search(r"struct\s+FrameBox\s*\{[^}]+\};", text, re.DOTALL)
    if struct_match:
        names.append(("FrameBox", "class", struct_match.group(0)))
    return names


def extract_shell_functions(text):
    found = []
    for match in SHELL_FUNCTION_RE.finditer(text):
        start = match.start()
        next_match = SHELL_FUNCTION_RE.search(text, match.end())
        end = next_match.start() if next_match else min(len(text), match.end() + 1200)
        found.append((match.group(1), "function", text[start:end].strip()))
    return found


def extract_functions(path, text):
    if path.suffix == ".py":
        return extract_python_functions(path, text)
    if path.suffix == ".ino":
        return extract_cpp_functions(text)
    if path.suffix == ".sh":
        return extract_shell_functions(text)
    return []


def extract_imports(path, text):
    imports = set()
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
            for item in ast.walk(tree):
                if isinstance(item, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in item.names)
                elif isinstance(item, ast.ImportFrom) and item.module:
                    imports.add(item.module.split(".")[0])
        except SyntaxError:
            pass
    elif path.suffix == ".ino":
        imports.update(INCLUDE_RE.findall(text))
    return sorted(imports)


def build_graph():
    nodes = {}
    edges = {}
    paths = [
        path
        for path in run_git_ls_files()
        if path.suffix.lower() in SOURCE_SUFFIXES and path.suffix.lower() not in BINARY_SUFFIXES
    ]

    image_count = len(list((ROOT / "docs" / "training_data").glob("*.png")))
    annotation_count = len(list((ROOT / "docs" / "training_data").glob("*.json")))
    if image_count or annotation_count:
        add_node(
            nodes,
            {
                "id": "module:docs/training_data",
                "type": "module",
                "name": "training_data",
                "filePath": "docs/training_data",
                "layer": "data",
                "summary": f"Captured blister-image dataset with {image_count} PNG images and {annotation_count} JSON annotation files.",
                "language": "Images/JSON",
                "tags": ["data", "training-data"],
                "complexity": "simple",
                "metadata": {"png_count": image_count, "json_count": annotation_count},
            },
        )

    file_text = {}
    functions_by_file = defaultdict(list)
    file_ids = {}
    known_modules = {}

    for rel_path in paths:
        abs_path = ROOT / rel_path
        text = read_text(abs_path)
        file_text[rel_path] = text
        file_type = node_type_for(rel_path)
        fid = node_id(file_type, str(rel_path))
        file_ids[str(rel_path)] = fid
        add_node(
            nodes,
            {
                "id": fid,
                "type": file_type,
                "name": rel_path.name,
                "filePath": str(rel_path),
                "layer": layer_for(rel_path),
                "summary": file_summary(rel_path, text),
                "language": language_for(rel_path),
                "tags": [layer_for(rel_path), file_category_for(rel_path), language_for(rel_path).lower()],
                "complexity": "moderate" if rel_path.suffix in {".ino", ".py"} else "simple",
                "metadata": {
                    "bytes": abs_path.stat().st_size,
                    "fileCategory": file_category_for(rel_path),
                },
            },
        )

        if str(rel_path).startswith("docs/training_data/"):
            add_edge(edges, "module:docs/training_data", fid, "contains", "contains metadata")

        for imported in extract_imports(rel_path, text):
            mid = known_modules.setdefault(imported, node_id("module", imported))
            add_node(
                nodes,
                {
                    "id": mid,
                    "type": "module",
                    "name": imported,
                    "filePath": imported,
                    "layer": "unknown",
                    "summary": f"External or platform dependency imported by project code: {imported}.",
                    "language": "Dependency",
                    "tags": ["dependency"],
                    "complexity": "simple",
                    "metadata": {},
                },
            )
            add_edge(edges, fid, mid, "imports")

        for func_name, func_type, code in extract_functions(rel_path, text):
            fn_id = node_id(func_type, f"{rel_path}:{func_name}")
            functions_by_file[str(rel_path)].append((func_name, fn_id, code))
            add_node(
                nodes,
                {
                    "id": fn_id,
                    "type": func_type,
                    "name": func_name,
                    "filePath": str(rel_path),
                    "layer": layer_for(rel_path),
                    "summary": function_summary(rel_path, func_name),
                    "code": code[:2400],
                    "language": language_for(rel_path),
                    "tags": [layer_for(rel_path), "symbol", language_for(rel_path).lower()],
                    "complexity": "moderate",
                    "metadata": {},
                },
            )
            add_edge(edges, fid, fn_id, "contains", "declares")

    functions_by_name = defaultdict(list)
    for rel, funcs in functions_by_file.items():
        for fn_name, fn_id, _code in funcs:
            functions_by_name[fn_name].append((rel, fn_id))

    for rel, funcs in functions_by_file.items():
        same_file = {fn_name: fn_id for fn_name, fn_id, _code in funcs}
        for fn_name, fn_id, code in funcs:
            for called_name, candidates in functions_by_name.items():
                if called_name == fn_name:
                    continue
                if re.search(rf"\b{re.escape(called_name)}\s*\(", code):
                    called_id = same_file.get(called_name)
                    if called_id is None and len(candidates) == 1:
                        called_id = candidates[0][1]
                    if called_id is None:
                        continue
                    add_edge(edges, fn_id, called_id, "calls")

    for rel_path, text in file_text.items():
        source = file_ids[str(rel_path)]
        for ref in sorted(set(SCRIPT_REF_RE.findall(text))):
            if ref in file_ids:
                add_edge(edges, source, file_ids[ref], "depends_on", "references script")
        for template in re.findall(r"render_template\([\"']([^\"']+)[\"']", text):
            target = f"scripts/templates/{template}"
            if target in file_ids:
                add_edge(edges, source, file_ids[target], "routes", "renders template")

    manual_edges = [
        ("scripts/upload.sh", "nano_33/nano_33.ino", "configures", "compiles/uploads"),
        ("scripts/monitor.sh", "nano_33/nano_33.ino", "depends_on", "serial monitor"),
        ("scripts/live_camera_view.py", "nano_33/nano_33.ino", "depends_on", "reads OVF1 stream"),
        ("scripts/data_collector.py", "nano_33/nano_33.ino", "depends_on", "captures OVF1 frames"),
        ("scripts/live_detect_view.py", "nano_33/nano_33.ino", "depends_on", "reads OVD1 stream"),
        ("scripts/detect_web.py", "nano_33/nano_33.ino", "serves", "reads OVD1 stream"),
        ("scripts/detect_data_collector.py", "nano_33/nano_33.ino", "serves", "reads detection stream"),
        ("scripts/test_training_data.py", "docs/training_data", "validates", "validates images"),
        ("scripts/data_collector.py", "docs/training_data", "writes_to", "writes images"),
        ("scripts/detect_data_collector.py", "docs/training_data", "writes_to", "writes images and metadata"),
        ("scripts/ei_deploy.sh", "nano_33/nano_33.ino", "configures", "installs model library"),
        ("README.md", "nano_33/nano_33.ino", "documents", "documents firmware"),
        ("README.md", "scripts/detect_web.sh", "documents", "documents command"),
        ("README.md", "scripts/test_training_data.py", "documents", "documents command"),
    ]
    for source_path, target_path, edge_type, label in manual_edges:
        source = file_ids.get(source_path)
        target = file_ids.get(target_path) or ("module:docs/training_data" if target_path == "docs/training_data" else None)
        if source and target:
            add_edge(edges, source, target, edge_type, label)

    layer_specs = {
        "api": {
            "id": "layer:firmware",
            "name": "Firmware",
            "description": "Arduino sketch code that captures camera frames, runs Edge Impulse inference, and owns the serial protocol.",
        },
        "service": {
            "id": "layer:host-tools",
            "name": "Host Tools",
            "description": "Python and shell tools that upload firmware, read serial packets, display detections, collect data, and validate models.",
        },
        "ui": {
            "id": "layer:browser-ui",
            "name": "Browser UI",
            "description": "Flask routes and HTML templates for browser-based viewing and data collection workflows.",
        },
        "data": {
            "id": "layer:data-and-research",
            "name": "Data and Research",
            "description": "Captured training metadata, analysis data, research notes, design reports, and onboarding tours.",
        },
        "utility": {
            "id": "layer:project-config",
            "name": "Project Config",
            "description": "Repository instructions, assistant notes, lock files, and support configuration.",
        },
        "unknown": {
            "id": "layer:external-dependencies",
            "name": "External Dependencies",
            "description": "External libraries, SDK headers, Python packages, Arduino libraries, and platform modules referenced by source files.",
        },
    }

    file_level_types = {"file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint"}
    layers = []
    for layer_key, spec in layer_specs.items():
        node_ids = [
            node["id"]
            for node in nodes.values()
            if node.get("layer") == layer_key and node.get("type") in file_level_types
        ]
        if node_ids:
            layers.append({**spec, "nodeIds": sorted(node_ids)})

    tour = [
        {
            "order": 1,
            "title": "Project Overview",
            "description": "Start with the README and repository instructions to understand the hardware target, model assumptions, commands, and generated-file hygiene.",
            "nodeIds": [file_ids.get("README.md"), file_ids.get("AGENTS.md")],
        },
        {
            "order": 2,
            "title": "Firmware Entry Point",
            "description": "Inspect the Arduino sketch entry points and serial command dispatcher that control streaming, counting, exposure presets, and diagnostics.",
            "nodeIds": [
                file_ids.get("nano_33/nano_33.ino"),
                node_id("function", "nano_33/nano_33.ino:setup"),
                node_id("function", "nano_33/nano_33.ino:loop"),
                node_id("function", "nano_33/nano_33.ino:handleSerialCommands"),
            ],
        },
        {
            "order": 3,
            "title": "Build and Model Deployment",
            "description": "Follow the upload and Edge Impulse deployment scripts that compile the sketch, enforce RAM limits, install model exports, and locate the board port.",
            "nodeIds": [
                file_ids.get("scripts/upload.sh"),
                file_ids.get("scripts/ei_deploy.sh"),
                file_ids.get("scripts/port.sh"),
            ],
        },
        {
            "order": 4,
            "title": "Detection Viewers",
            "description": "Trace OVD1 detection packet consumers from Python parsers through OpenCV and browser display workflows.",
            "nodeIds": [
                file_ids.get("scripts/detect_web.py"),
                file_ids.get("scripts/live_detect_view.py"),
                file_ids.get("scripts/templates/detect.html"),
            ],
        },
        {
            "order": 5,
            "title": "Data Collection and Validation",
            "description": "Review how training captures, detection-assisted metadata, and local model checks connect to the firmware preprocessing assumptions.",
            "nodeIds": [
                "module:docs/training_data",
                file_ids.get("scripts/data_collector.py"),
                file_ids.get("scripts/detect_data_collector.py"),
                file_ids.get("scripts/test_training_data.py"),
            ],
        },
    ]
    existing_ids = set(nodes)
    for step in tour:
        step["nodeIds"] = [node_id for node_id in step["nodeIds"] if node_id in existing_ids]

    analyzed_at = datetime.now(timezone.utc).isoformat()
    commit_hash = git_commit_hash()

    return {
        "version": "1.0.0",
        "project": {
            "name": "Nano 33 Medicine Counting",
            "languages": sorted(
                {
                    node["language"]
                    for node in nodes.values()
                    if node.get("language") not in {"Dependency", "Images/JSON"}
                }
            ),
            "frameworks": ["Arduino", "Edge Impulse", "Flask", "OpenCV", "pyserial"],
            "description": "Arduino Nano 33 BLE and OV7675 camera project for on-device medicine blister-cell counting with an Edge Impulse FOMO model and host-side serial viewers.",
            "analyzedAt": analyzed_at,
            "gitCommitHash": commit_hash,
        },
        "nodes": sorted(nodes.values(), key=lambda node: (node["type"], node["filePath"], node["name"])),
        "edges": sorted(edges.values(), key=lambda edge: edge["id"]),
        "layers": layers,
        "tour": tour,
        "metadata": {
            "generator": "scripts/generate_understand_graph.py",
            "projectRoot": str(ROOT),
        },
    }


def build_dashboard(graph):
    graph_json = html.escape(json.dumps(graph, separators=(",", ":")), quote=False)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nano 33 Knowledge Graph</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --text: #17202a;
  --muted: #647282;
  --line: #d7dde5;
  --api: #2176ae;
  --service: #1b998b;
  --data: #8a5a44;
  --ui: #d95d39;
  --utility: #6d597a;
  --unknown: #7d8790;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
}}
header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}}
h1 {{ margin: 0; font-size: 18px; font-weight: 650; }}
.meta {{ color: var(--muted); font-size: 13px; }}
.app {{
  display: grid;
  grid-template-columns: 320px 1fr 360px;
  height: calc(100vh - 58px);
  min-height: 620px;
}}
aside, main {{
  min-width: 0;
  overflow: hidden;
}}
aside {{
  background: var(--panel);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
}}
.right {{ border-left: 1px solid var(--line); border-right: 0; }}
.section {{ padding: 14px; border-bottom: 1px solid var(--line); }}
input {{
  width: 100%;
  padding: 10px 11px;
  border: 1px solid var(--line);
  border-radius: 6px;
  font: inherit;
}}
.counts {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}}
.count {{
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px;
  background: #fbfcfd;
}}
.count strong {{ display: block; font-size: 18px; }}
.count span {{ color: var(--muted); font-size: 12px; }}
.list {{
  overflow: auto;
  padding: 8px;
}}
.node-row {{
  display: block;
  width: 100%;
  text-align: left;
  border: 0;
  background: transparent;
  padding: 9px 8px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text);
}}
.node-row:hover, .node-row.active {{ background: #eef3f6; }}
.node-row b {{ display: block; font-size: 13px; overflow-wrap: anywhere; }}
.node-row span {{ color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }}
main {{
  position: relative;
  background: #fbfcfd;
}}
svg {{
  width: 100%;
  height: 100%;
  display: block;
}}
.edge {{ stroke: #c4ccd6; stroke-width: 1; opacity: .55; }}
.node {{ cursor: pointer; stroke: #fff; stroke-width: 2; }}
.label {{ pointer-events: none; font-size: 11px; fill: #27313b; text-anchor: middle; }}
.legend {{
  position: absolute;
  left: 12px;
  bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  background: rgba(255,255,255,.92);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px;
  font-size: 12px;
}}
.swatch {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 4px; }}
.details {{
  overflow: auto;
  padding: 16px;
}}
.details h2 {{ margin: 0 0 6px; font-size: 18px; overflow-wrap: anywhere; }}
.pill {{
  display: inline-block;
  border-radius: 999px;
  padding: 3px 8px;
  margin: 0 5px 8px 0;
  background: #eef3f6;
  color: #334250;
  font-size: 12px;
}}
.summary {{ line-height: 1.45; }}
pre {{
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: #101820;
  color: #f4f7fb;
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.35;
}}
.rel button {{
  display: block;
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  padding: 7px 0;
  color: #1f5f8b;
  cursor: pointer;
}}
@media (max-width: 980px) {{
  .app {{ grid-template-columns: 1fr; height: auto; }}
  aside, main {{ min-height: 420px; border-right: 0; border-bottom: 1px solid var(--line); }}
}}
</style>
</head>
<body>
<header>
  <h1>Nano 33 Knowledge Graph</h1>
  <div class="meta" id="generated"></div>
</header>
<div class="app">
  <aside>
    <div class="section">
      <input id="search" placeholder="Search files, functions, summaries">
      <div class="counts" id="counts"></div>
    </div>
    <div class="list" id="nodeList"></div>
  </aside>
  <main>
    <svg id="graph" role="img" aria-label="Knowledge graph"></svg>
    <div class="legend" id="legend"></div>
  </main>
  <aside class="right">
    <div class="details" id="details"></div>
  </aside>
</div>
<script type="application/json" id="graph-data">{graph_json}</script>
<script>
const graph = JSON.parse(document.getElementById('graph-data').textContent);
const color = {{
  api: '#2176ae',
  service: '#1b998b',
  data: '#8a5a44',
  ui: '#d95d39',
  utility: '#6d597a',
  unknown: '#7d8790'
}};
let selectedId = graph.nodes.find(n => n.filePath === 'README.md')?.id || graph.nodes[0]?.id;
let query = '';
const byId = new Map(graph.nodes.map(n => [n.id, n]));
const incoming = new Map();
const outgoing = new Map();
for (const edge of graph.edges) {{
  if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
  if (!incoming.has(edge.target)) incoming.set(edge.target, []);
  outgoing.get(edge.source).push(edge);
  incoming.get(edge.target).push(edge);
}}
document.getElementById('generated').textContent =
  `${{graph.nodes.length}} nodes | ${{graph.edges.length}} edges | generated ${{new Date(graph.project.analyzedAt).toLocaleString()}}`;
document.getElementById('search').addEventListener('input', event => {{
  query = event.target.value.toLowerCase();
  render();
}});
function visibleNodes() {{
  if (!query) return graph.nodes;
  return graph.nodes.filter(n =>
    [n.name, n.filePath, n.type, n.layer, n.summary].join(' ').toLowerCase().includes(query)
  );
}}
function renderCounts() {{
  const counts = {{}};
  for (const node of graph.nodes) counts[node.layer] = (counts[node.layer] || 0) + 1;
  document.getElementById('counts').innerHTML = Object.entries(counts)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([layer, count]) => `<div class="count"><strong>${{count}}</strong><span>${{layer}}</span></div>`)
    .join('');
}}
function renderList(nodes) {{
  document.getElementById('nodeList').innerHTML = nodes
    .map(n => `<button class="node-row ${{n.id === selectedId ? 'active' : ''}}" data-id="${{n.id}}">
      <b>${{escapeHtml(n.name)}}</b><span>${{escapeHtml(n.type)}} | ${{escapeHtml(n.filePath)}}</span>
    </button>`)
    .join('');
  document.querySelectorAll('.node-row').forEach(button => button.addEventListener('click', () => {{
    selectedId = button.dataset.id;
    render();
  }}));
}}
function renderGraph(nodes) {{
  const svg = document.getElementById('graph');
  const w = svg.clientWidth || 900;
  const h = svg.clientHeight || 640;
  const layers = ['api', 'service', 'ui', 'data', 'utility', 'unknown'];
  const grouped = new Map(layers.map(layer => [layer, []]));
  for (const node of nodes) {{
    if (!grouped.has(node.layer)) grouped.set(node.layer, []);
    grouped.get(node.layer).push(node);
  }}
  const pos = new Map();
  layers.forEach((layer, col) => {{
    const items = grouped.get(layer) || [];
    const x = 90 + col * Math.max(120, (w - 180) / Math.max(1, layers.length - 1));
    items.forEach((node, row) => {{
      const y = 58 + row * Math.max(34, (h - 116) / Math.max(1, items.length - 1 || 1));
      pos.set(node.id, {{x, y}});
    }});
  }});
  const visible = new Set(nodes.map(n => n.id));
  const edgeMarkup = graph.edges
    .filter(e => visible.has(e.source) && visible.has(e.target) && pos.has(e.source) && pos.has(e.target))
    .slice(0, 900)
    .map(e => {{
      const s = pos.get(e.source), t = pos.get(e.target);
      return `<line class="edge" x1="${{s.x}}" y1="${{s.y}}" x2="${{t.x}}" y2="${{t.y}}"></line>`;
    }}).join('');
  const nodeMarkup = nodes.map(n => {{
    const p = pos.get(n.id);
    const r = n.type === 'file' ? 8 : n.type === 'module' ? 7 : 5;
    return `<g data-id="${{n.id}}">
      <circle class="node" cx="${{p.x}}" cy="${{p.y}}" r="${{r}}" fill="${{color[n.layer] || color.unknown}}"></circle>
      <text class="label" x="${{p.x}}" y="${{p.y + 18}}">${{escapeHtml(shortName(n.name))}}</text>
    </g>`;
  }}).join('');
  svg.innerHTML = edgeMarkup + nodeMarkup;
  svg.querySelectorAll('g[data-id]').forEach(item => item.addEventListener('click', () => {{
    selectedId = item.dataset.id;
    render();
  }}));
}}
function renderDetails() {{
  const node = byId.get(selectedId);
  if (!node) return;
  const outs = outgoing.get(node.id) || [];
  const ins = incoming.get(node.id) || [];
  document.getElementById('details').innerHTML = `
    <h2>${{escapeHtml(node.name)}}</h2>
    <span class="pill">${{escapeHtml(node.type)}}</span>
    <span class="pill">${{escapeHtml(node.layer)}}</span>
    <span class="pill">${{escapeHtml(node.language || '')}}</span>
    <p class="meta">${{escapeHtml(node.filePath)}}</p>
    <p class="summary">${{escapeHtml(node.summary)}}</p>
    ${{renderRelations('Outgoing', outs, 'target')}}
    ${{renderRelations('Incoming', ins, 'source')}}
    ${{node.code ? `<h3>Code</h3><pre>${{escapeHtml(node.code)}}</pre>` : ''}}
  `;
  document.querySelectorAll('.rel button').forEach(button => button.addEventListener('click', () => {{
    selectedId = button.dataset.id;
    render();
  }}));
}}
function renderRelations(title, edges, side) {{
  if (!edges.length) return '';
  return `<h3>${{title}}</h3><div class="rel">` + edges.slice(0, 30).map(edge => {{
    const other = byId.get(edge[side]);
    if (!other) return '';
    return `<button data-id="${{other.id}}">${{escapeHtml(edge.type)}} ${{edge.label ? `(${{escapeHtml(edge.label)}})` : ''}} -> ${{escapeHtml(other.name)}}</button>`;
  }}).join('') + `</div>`;
}}
function renderLegend() {{
  document.getElementById('legend').innerHTML = Object.keys(color)
    .map(layer => `<span><i class="swatch" style="background:${{color[layer]}}"></i>${{layer}}</span>`)
    .join('');
}}
function escapeHtml(value) {{
  return String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
}}
function shortName(name) {{
  const text = String(name);
  return text.length > 18 ? text.slice(0, 17) + '...' : text;
}}
function render() {{
  const nodes = visibleNodes();
  renderCounts();
  renderList(nodes);
  renderGraph(nodes);
  renderDetails();
  renderLegend();
}}
render();
</script>
</body>
</html>
"""


def main():
    graph = build_graph()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    GRAPH_PATH.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    DASHBOARD_PATH.write_text(build_dashboard(graph), encoding="utf-8")
    file_level_types = {"file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint"}
    analyzed_files = len(
        {
            node["filePath"]
            for node in graph["nodes"]
            if node["type"] in file_level_types and node.get("filePath")
        }
    )
    META_PATH.write_text(
        json.dumps(
            {
                "lastAnalyzedAt": graph["project"]["analyzedAt"],
                "gitCommitHash": graph["project"]["gitCommitHash"],
                "version": graph["version"],
                "analyzedFiles": analyzed_files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"nodes={len(graph['nodes'])} edges={len(graph['edges'])}")
    print(f"graph={GRAPH_PATH}")
    print(f"dashboard={DASHBOARD_PATH}")
    print(f"meta={META_PATH}")


if __name__ == "__main__":
    main()
