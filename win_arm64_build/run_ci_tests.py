#!/usr/bin/env python
"""Run the CI Python wheel test suite against the installed win_arm64 wheel.

Mirrors the Bazel `//python/dist:test_wheel` (protobuftests) + `test_upb.yml`
`test_wheels` job, without Bazel:

  1. protoc-generate the test *_pb2.py into the installed protobuf package
     (site-packages/google/...), where pip-installing protobuftests would put them.
  2. copy the test sources (*_test.py, test_util.py, import_test_package, numpy)
     into site-packages/google/protobuf/internal.
  3. run `python -m unittest` over every packaged *_test.py, excluding the same
     tests CI excludes (-e _pybind11_test.py -e proto_api_test.py; C++/pybind only).

Requires the PROTOC env var. Run with the protobuf wheel already installed in the
active interpreter.
"""
import os
import shutil
import subprocess
import sys
import sysconfig

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_repo_root(start):
    d = start
    while True:
        if os.path.exists(os.path.join(d, "MODULE.bazel")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise SystemExit("repo root (MODULE.bazel) not found")
        d = parent


REPO = find_repo_root(SCRIPT_DIR)
SRC = os.path.join(REPO, "src")
PYDIR = os.path.join(REPO, "python")
JAVA_RES = os.path.join(REPO, "java", "core", "src", "main", "resources")
SITE = sysconfig.get_paths()["purelib"]
INTERNAL = os.path.join(SITE, "google", "protobuf", "internal")
# Tests run with cwd=STAGE so test_util.GoldenFile() reads LF-normalized golden
# files (the repo checkout has CRLF golden .txt on Windows via git autocrlf).
STAGE = os.path.join(SCRIPT_DIR, "_teststage")
TESTDATA_SRC = os.path.join(SRC, "google", "protobuf", "testdata")

SRC_TEST_PROTOS = [
    "any_test.proto", "map_proto2_unittest.proto", "map_unittest.proto",
    "unittest.proto", "unittest_custom_options.proto", "unittest_empty.proto",
    "unittest_enormous_descriptor.proto", "unittest_import.proto",
    "unittest_import_public.proto", "unittest_mset.proto",
    "unittest_mset_wire_format.proto", "unittest_no_generic_services.proto",
    "unittest_proto3.proto", "unittest_proto3_arena.proto",
    "unittest_proto3_optional.proto", "unittest_well_known_types.proto",
    "unittest_features.proto", "unittest_custom_features.proto",
    "unittest_retention.proto", "unittest_string_type.proto",
    "unittest_proto3_extensions.proto", "cpp_features.proto",
    "unittest_import_option.proto", "unittest_delimited.proto",
    "unittest_delimited_import.proto", "unittest_legacy_features.proto",
    "unittest_no_field_presence.proto",
]
UTIL_TEST_PROTOS = ["json_format.proto", "json_format_proto3.proto"]
JSON_TEST_PROTOS = ["json_enumval_custom_string.proto"]
WKT_PROTOS = [
    "descriptor.proto", "any.proto", "api.proto", "duration.proto",
    "empty.proto", "field_mask.proto", "source_context.proto", "struct.proto",
    "timestamp.proto", "type.proto", "wrappers.proto",
    "json_options.proto", "json_enumvalue_options.proto",
]

SKIP_TESTS = {"proto_api_test"}
SKIP_SUFFIXES = ("_pybind11_test",)


def _protoc():
    p = os.environ.get("PROTOC")
    if not p or not os.path.exists(p):
        raise SystemExit("Set PROTOC env var to a protoc.exe path")
    return p


def _uses_unsupported_edition(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s.startswith("edition"):
                    return any(y in s for y in ("2027", "2028"))
    except OSError:
        pass
    return False


def gen_protos():
    protos = [os.path.join(SRC, "google", "protobuf", n) for n in SRC_TEST_PROTOS + WKT_PROTOS]
    protos += [os.path.join(SRC, "google", "protobuf", "util", n) for n in UTIL_TEST_PROTOS]
    protos += [os.path.join(SRC, "google", "protobuf", "json", n) for n in JSON_TEST_PROTOS]
    for root, _dirs, files in os.walk(os.path.join(PYDIR, "google", "protobuf", "internal")):
        for f in files:
            if f.endswith(".proto"):
                protos.append(os.path.join(root, f))
    protos = [p for p in protos if os.path.exists(p)]
    kept, skipped = [], []
    for p in protos:
        (skipped if _uses_unsupported_edition(p) else kept).append(p)
    if skipped:
        print("skipping edition>2026 protos:", ", ".join(os.path.basename(p) for p in skipped))
    cmd = [_protoc(), "--python_out=" + SITE, "--proto_path=" + SRC,
           "--proto_path=" + PYDIR, "--proto_path=" + JAVA_RES] + kept
    print("protoc: generating %d protos -> %s" % (len(kept), SITE))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("PROTOC STDERR:\n", r.stderr)
        raise SystemExit("protoc failed")
    for sub in ("json", "util"):
        d = os.path.join(SITE, "google", "protobuf", sub)
        if os.path.isdir(d) and not os.path.exists(os.path.join(d, "__init__.py")):
            open(os.path.join(d, "__init__.py"), "w").close()
    print("protoc: OK")


def copy_test_sources():
    src_internal = os.path.join(PYDIR, "google", "protobuf", "internal")
    n = 0
    for root, _dirs, files in os.walk(src_internal):
        rel = os.path.relpath(root, src_internal)
        for f in files:
            if f.endswith(".py") and (
                f.endswith("_test.py") or f == "test_util.py"
                or rel.startswith("import_test_package") or rel.startswith("numpy")
                or f == "testing_refleaks.py" or f == "_parameterized.py"
            ):
                dst_dir = INTERNAL if rel == "." else os.path.join(INTERNAL, rel)
                os.makedirs(dst_dir, exist_ok=True)
                shutil.copy2(os.path.join(root, f), os.path.join(dst_dir, f))
                n += 1
    print("copied %d test source files -> %s" % (n, INTERNAL))


def collect_test_modules():
    mods = []
    for f in sorted(os.listdir(INTERNAL)):
        if not f.endswith("_test.py"):
            continue
        name = f[:-3]
        if name in SKIP_TESTS or name.endswith(SKIP_SUFFIXES):
            continue
        mods.append("google.protobuf.internal." + name)
    if os.path.exists(os.path.join(INTERNAL, "numpy", "numpy_test.py")):
        mods.append("google.protobuf.internal.numpy.numpy_test")
    return mods


def stage_testdata():
    dst = os.path.join(STAGE, "src", "google", "protobuf", "testdata")
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(dst)
    n_txt = n_bin = 0
    for f in os.listdir(TESTDATA_SRC):
        sp = os.path.join(TESTDATA_SRC, f)
        if not os.path.isfile(sp):
            continue
        dp = os.path.join(dst, f)
        if f.endswith(".txt"):
            with open(sp, "rb") as fh:
                data = fh.read().replace(b"\r\n", b"\n")
            with open(dp, "wb") as fh:
                fh.write(data)
            n_txt += 1
        else:
            shutil.copy2(sp, dp)
            n_bin += 1
    print("staged testdata -> %s (%d .txt normalized, %d binary)" % (dst, n_txt, n_bin))


def main():
    gen_protos()
    copy_test_sources()
    stage_testdata()
    mods = collect_test_modules()
    print("\nRunning %d test modules...\n" % len(mods))
    failed = []
    total = 0
    for m in mods:
        r = subprocess.run([sys.executable, "-m", "unittest", "-q", m],
                           cwd=STAGE, capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        ran = next((ln for ln in out.splitlines() if ln.startswith("Ran ")), "")
        status = "OK" if r.returncode == 0 else "FAIL"
        if r.returncode != 0:
            failed.append((m, out))
        print("[%-4s] %s  %s" % (status, m, ran))

    print("\n================ SUMMARY ================")
    print("modules passed: %d/%d" % (len(mods) - len(failed), len(mods)))
    for m, out in failed:
        print("\n----- %s -----" % m)
        print("\n".join(out.strip().splitlines()[-25:]))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
