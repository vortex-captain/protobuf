#!/usr/bin/env python
"""Build the protobuf Python win_arm64 (cp311-abi3) wheel WITHOUT Bazel.

The upstream Bazel build cannot build the Python extension on a Windows host
(python/dist/system_python.bzl marks Windows "Unsupported"), so Windows wheels
are normally cross-compiled from Linux. This script builds the win_arm64 wheel
natively on a Windows ARM64 host with setuptools + MSVC instead, using only
files checked into the repo plus a prebuilt protoc.

Pipeline (all output under win_arm64_build/_build):
  1. assemble  - lay out upb + utf8_range + python bindings + checked-in
     descriptor minitables + pure-python runtime into the layout setup.py wants.
  2. generate  - protoc-generate WKT _pb2.py, python_edition_defaults.py, and a
     minimal descriptor.upbdefs.{h,c} shim (upb's protoc-gen-upbdefs is Bazel-only;
     descriptor_pool.c only needs FileDescriptorProto_getmsgdef).
  3. patch      - one MSVC-compat source tweak (empty FreeThreadingMutex struct).
  4. build      - setup.py bdist_wheel --py-limited-api cp311 (abi3).

Requires the PROTOC env var to point at a protoc.exe (its gencode version must be
<= the runtime version 7.37; protoc 35.1/36.0 emit 7.35/7.36).
"""
import os
import shutil
import subprocess
import sys

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
BUILD_DIR = os.path.join(SCRIPT_DIR, "_build")
SRC = os.path.join(REPO, "src")
PYDIR = os.path.join(REPO, "python")

UPB_SUBDIRS = [
    "base", "hash", "lex", "mem", "message", "mini_descriptor",
    "mini_table", "port", "reflection", "text", "util", "wire",
]
UPB_EXTS = (".c", ".h", ".hpp", ".inc")
REFLECTION_EXCLUDE_DIRS = {"stage0", "cmake"}

PY_SRC_EXCLUDE_FILES = {
    os.path.normpath("google/protobuf/internal/test_util.py"),
    os.path.normpath("google/protobuf/internal/import_test_package/__init__.py"),
}

WKT_PROTOS = [
    "google/protobuf/descriptor.proto",
    "google/protobuf/any.proto", "google/protobuf/api.proto",
    "google/protobuf/duration.proto", "google/protobuf/empty.proto",
    "google/protobuf/field_mask.proto", "google/protobuf/source_context.proto",
    "google/protobuf/struct.proto", "google/protobuf/timestamp.proto",
    "google/protobuf/type.proto", "google/protobuf/wrappers.proto",
    "google/protobuf/json_options.proto",
    "google/protobuf/json_enumvalue_options.proto",
    "google/protobuf/compiler/plugin.proto",
]


def _copy(src, rel):
    dst = os.path.join(BUILD_DIR, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def _run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write((r.stdout or "") + (r.stderr or ""))
        raise SystemExit("command failed: %s" % (cmd[0],))
    return r


# --------------------------------------------------------------------------- #
# 1. assemble                                                                  #
# --------------------------------------------------------------------------- #
def assemble():
    if os.path.isdir(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR)

    count = 0
    for sub in UPB_SUBDIRS:
        root = os.path.join(REPO, "upb", sub)
        for dirpath, dirnames, filenames in os.walk(root):
            if sub == "reflection":
                top = os.path.relpath(dirpath, root).split(os.sep)[0]
                if top in REFLECTION_EXCLUDE_DIRS:
                    dirnames[:] = []
                    continue
            for fn in filenames:
                if fn.endswith(UPB_EXTS):
                    src = os.path.join(dirpath, fn)
                    _copy(src, os.path.relpath(src, REPO))
                    count += 1
    for fn in os.listdir(os.path.join(REPO, "upb")):
        if fn.endswith(".h"):
            _copy(os.path.join(REPO, "upb", fn), os.path.join("upb", fn))
            count += 1
    print("upb: copied %d files" % count)

    for fn in ["utf8_range.c", "utf8_range.h", "utf8_range_neon.inc", "utf8_range_sse.inc"]:
        _copy(os.path.join(REPO, "third_party", "utf8_range", fn), os.path.join("utf8_range", fn))

    n = 0
    for fn in os.listdir(PYDIR):
        if fn.endswith((".c", ".h")):
            _copy(os.path.join(PYDIR, fn), os.path.join("python", fn))
            n += 1
    print("python bindings: copied %d files" % n)

    cmk = os.path.join(REPO, "upb", "reflection", "cmake", "google", "protobuf")
    for fn in ["descriptor.upb.h", "descriptor.upb_minitable.h", "descriptor.upb_minitable.c"]:
        _copy(os.path.join(cmk, fn), os.path.join("google", "protobuf", fn))

    _copy(os.path.join(PYDIR, "google", "__init__.py"), os.path.join("google", "__init__.py"))
    n = 0
    for dirpath, _dirs, filenames in os.walk(os.path.join(PYDIR, "google", "protobuf")):
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, PYDIR)
            norm = os.path.normpath(rel)
            if fn.endswith("_test.py") and (os.sep + "internal" + os.sep) in (os.sep + norm):
                continue
            if norm in PY_SRC_EXCLUDE_FILES:
                continue
            _copy(src, rel)
            n += 1
    print("pure python: copied %d files" % n)

    _copy(os.path.join(PYDIR, "google", "protobuf", "breaking_changes.h"),
          os.path.join("google", "protobuf", "breaking_changes.h"))
    _copy(os.path.join(REPO, "LICENSE"), "LICENSE")
    if os.path.exists(os.path.join(PYDIR, "README.md")):
        _copy(os.path.join(PYDIR, "README.md"), "README.md")
    _copy(os.path.join(PYDIR, "dist", "MANIFEST.in"), "MANIFEST.in")
    # setup.py + msvc_compat.h are checked in next to this script.
    _copy(os.path.join(SCRIPT_DIR, "setup.py"), "setup.py")
    _copy(os.path.join(SCRIPT_DIR, "msvc_compat.h"), "msvc_compat.h")
    print("assembled source tree at %s" % BUILD_DIR)


# --------------------------------------------------------------------------- #
# 2. generate                                                                  #
# --------------------------------------------------------------------------- #
def generate(protoc):
    _run([protoc, "--python_out=" + BUILD_DIR, "--proto_path=" + SRC] + WKT_PROTOS)
    print("generated %d WKT/plugin _pb2.py" % len(WKT_PROTOS))

    binpb = os.path.join(BUILD_DIR, "_defaults.binpb")
    _run([protoc, "--edition_defaults_out=" + binpb,
          "--edition_defaults_minimum=PROTO2", "--edition_defaults_maximum=2026",
          "--proto_path=" + SRC, os.path.join(SRC, "google", "protobuf", "descriptor.proto")])
    with open(binpb, "rb") as f:
        data = f.read()
    os.remove(binpb)
    tmpl = os.path.join(PYDIR, "google", "protobuf", "internal",
                        "python_edition_defaults.py.template")
    with open(tmpl, "r", encoding="utf-8") as f:
        content = f.read()
    out = content.replace("DEFAULTS_VALUE", "".join("\\x%02x" % b for b in data))
    g = {}
    exec(out, g)  # sanity round-trip
    assert g["_PROTOBUF_INTERNAL_PYTHON_EDITION_DEFAULTS"] == data
    with open(os.path.join(BUILD_DIR, "google", "protobuf", "internal",
                           "python_edition_defaults.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print("generated python_edition_defaults.py (%d bytes)" % len(data))

    _gen_upbdefs_shim(protoc)


def _gen_upbdefs_shim(protoc):
    setpb = os.path.join(BUILD_DIR, "_descriptor_set.pb")
    _run([protoc, "--descriptor_set_out=" + setpb, "--proto_path=" + SRC,
          os.path.join(SRC, "google", "protobuf", "descriptor.proto")])
    with open(setpb, "rb") as f:
        data = f.read()
    os.remove(setpb)
    lines = ["    " + "".join("0x%02x," % b for b in data[i:i + 16])
             for i in range(0, len(data), 16)]
    gp = os.path.join(BUILD_DIR, "google", "protobuf")
    with open(os.path.join(gp, "descriptor.upbdefs.h"), "w", encoding="utf-8", newline="\n") as f:
        f.write(_UPBDEFS_H)
    with open(os.path.join(gp, "descriptor.upbdefs.c"), "w", encoding="utf-8", newline="\n") as f:
        f.write(_UPBDEFS_C % "\n".join(lines))
    print("generated descriptor.upbdefs.h/.c (%d bytes embedded)" % len(data))


_UPBDEFS_H = '''/* Minimal replacement for the upb-generated google/protobuf/descriptor.upbdefs.h.
 * python/descriptor_pool.c only uses google_protobuf_FileDescriptorProto_getmsgdef();
 * this header exposes just that symbol (the upstream file, produced by upb's
 * Bazel-only protoc-gen-upbdefs plugin, declares one per descriptor.proto message).
 */
#ifndef GOOGLE_PROTOBUF_DESCRIPTOR_PROTO_UPBDEFS_H__SHIM_
#define GOOGLE_PROTOBUF_DESCRIPTOR_PROTO_UPBDEFS_H__SHIM_

#include "upb/reflection/def.h"

#ifdef __cplusplus
extern "C" {
#endif

const upb_MessageDef* google_protobuf_FileDescriptorProto_getmsgdef(
    upb_DefPool* s);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif  /* GOOGLE_PROTOBUF_DESCRIPTOR_PROTO_UPBDEFS_H__SHIM_ */
'''

_UPBDEFS_C = '''/* Minimal replacement for the upb-generated google/protobuf/descriptor.upbdefs.c.
 * Loads descriptor.proto (embedded serialized FileDescriptorSet from protoc
 * --descriptor_set_out) into the given upb_DefPool using the checked-in descriptor
 * minitables, then returns the FileDescriptorProto def -- functionally equivalent
 * for the duplicate-file comparison descriptor_pool.c performs.
 */
#include "google/protobuf/descriptor.upbdefs.h"

#include <stddef.h>

#include "google/protobuf/descriptor.upb.h"
#include "upb/base/status.h"
#include "upb/mem/arena.h"
#include "upb/reflection/def.h"

static const char kDescriptorSet[] = {
%s
};

const upb_MessageDef* google_protobuf_FileDescriptorProto_getmsgdef(
    upb_DefPool* s) {
  const upb_MessageDef* m =
      upb_DefPool_FindMessageByName(s, "google.protobuf.FileDescriptorProto");
  if (m) return m;

  upb_Arena* arena = upb_Arena_New();
  if (!arena) return NULL;
  google_protobuf_FileDescriptorSet* set = google_protobuf_FileDescriptorSet_parse(
      kDescriptorSet, sizeof(kDescriptorSet), arena);
  if (set) {
    size_t n = 0;
    const google_protobuf_FileDescriptorProto* const* files =
        google_protobuf_FileDescriptorSet_file(set, &n);
    upb_Status status;
    upb_Status_Clear(&status);
    for (size_t i = 0; i < n; i++) {
      upb_DefPool_AddFile(s, files[i], &status);
    }
  }
  upb_Arena_Free(arena);
  return upb_DefPool_FindMessageByName(s, "google.protobuf.FileDescriptorProto");
}
'''


# --------------------------------------------------------------------------- #
# 3. patch (MSVC empty-struct)                                                 #
# --------------------------------------------------------------------------- #
def patch_msvc():
    path = os.path.join(BUILD_DIR, "python", "protobuf.c")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    old = ("typedef struct {\n"
           "#ifdef ENABLE_MUTEX\n"
           "  pthread_mutex_t mutex;\n"
           "#endif\n"
           "} FreeThreadingMutex;")
    new = ("typedef struct {\n"
           "#ifdef ENABLE_MUTEX\n"
           "  pthread_mutex_t mutex;\n"
           "#else\n"
           "  char unused_msvc_placeholder_;  /* MSVC forbids empty structs in C */\n"
           "#endif\n"
           "} FreeThreadingMutex;")
    if old in text:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.replace(old, new))
        print("patched empty FreeThreadingMutex struct")
    else:
        print("protobuf.c: empty-struct pattern not found (already patched or changed)")


# --------------------------------------------------------------------------- #
# 4. build                                                                     #
# --------------------------------------------------------------------------- #
def build():
    # setuptools/wheel are needed to build the wheel. Install if pip is available
    # (CI's setup-python has pip); ignore failures where pip is absent (e.g. a uv
    # venv) and rely on them already being present.
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "setuptools", "wheel"],
                   check=False)
    subprocess.run([sys.executable, "setup.py", "bdist_wheel", "--py-limited-api", "cp311"],
                   cwd=BUILD_DIR, check=True)
    dist = os.path.join(BUILD_DIR, "dist")
    wheels = [f for f in os.listdir(dist) if f.endswith(".whl")]
    print("\nBuilt wheel(s): %s" % ", ".join(wheels))
    print("WHEEL_DIR=%s" % dist)


def main():
    protoc = os.environ.get("PROTOC")
    if not protoc or not os.path.exists(protoc):
        raise SystemExit("Set PROTOC env var to a protoc.exe path")
    assemble()
    generate(protoc)
    patch_msvc()
    build()


if __name__ == "__main__":
    main()
