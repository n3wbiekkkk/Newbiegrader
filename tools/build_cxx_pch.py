#!/usr/bin/env python3
"""Build a GCC precompiled header for <bits/stdc++.h>.

Run this once per judge image/toolchain update, as root:

    sudo python3 tools/build_cxx_pch.py

The grader passes ``-I <dest>`` for C++ compiles only when the PCH exists.
Keeping the PCH outside the job workspace makes it read-only to submissions.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


DEFAULT_DEST = "/usr/local/lib/newbiegrader/pch/cxx"


def find_header(compiler: str) -> Path:
    probe = subprocess.run(
        [compiler, "-E", "-x", "c++", "-H", "-"],
        input="#include <bits/stdc++.h>\n",
        text=True,
        capture_output=True,
        check=False,
    )
    for line in probe.stderr.splitlines():
        fields = line.split()
        if fields and fields[-1].endswith("/bits/stdc++.h"):
            path = Path(fields[-1])
            if path.is_file():
                return path
    raise SystemExit(
        f"cannot locate <bits/stdc++.h> with {compiler}; install the C++ headers"
    )


def build(compiler: str, dest: Path) -> None:
    header = find_header(compiler)
    dest = dest.resolve()
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix=".cxx-pch-", dir=parent))
    try:
        bits = tmp / "bits"
        bits.mkdir(mode=0o755)
        link = bits / "stdc++.h"
        link.symlink_to(header)
        gch = bits / "stdc++.h.gch"
        subprocess.run(
            [compiler, "-O2", "-std=c++17", "-x", "c++-header",
             str(link), "-o", str(gch)],
            check=True,
        )
        gch.chmod(0o644)

        # Prove GCC actually selected the PCH rather than silently falling
        # back to parsing the header. -H prefixes a used PCH with '!'.
        probe = subprocess.run(
            [compiler, "-I", str(tmp), "-O2", "-std=c++17", "-Wall", "-Wextra",
             "-H", "-fsyntax-only", "-x", "c++", "-"],
            input="#include <bits/stdc++.h>\nint main(){return 0;}\n",
            text=True,
            capture_output=True,
            check=False,
        )
        used = any(line.lstrip().startswith("!")
                   and "stdc++.h.gch" in line
                   for line in probe.stderr.splitlines())
        if probe.returncode != 0 or not used:
            raise SystemExit(
                "PCH verification failed: GCC did not use the generated header\n"
                + probe.stderr[-2000:]
            )

        size = gch.stat().st_size
        old = dest.with_name(dest.name + ".old")
        if old.exists():
            shutil.rmtree(old)
        if dest.exists():
            dest.rename(old)
        tmp.rename(dest)
        dest.chmod(0o755)   # compile sandbox runs as an unprivileged UID
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
        print(f"PCH ready: {dest / 'bits' / 'stdc++.h.gch'} "
              f"({size} bytes, from {header})")
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default=os.environ.get("CXX", "g++"))
    parser.add_argument("--dest", default=os.environ.get("GRADER_CXX_PCH_DIR", DEFAULT_DEST))
    args = parser.parse_args()
    try:
        build(args.compiler, Path(args.dest))
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"PCH build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
