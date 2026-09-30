# Embedded Python Runtime Licenses

AQA packages the `install_only` artifacts from `astral-sh/python-build-standalone` release `20260623`, containing CPython 3.13.14 and target-specific native libraries. The six archive URLs and SHA-256 digests are pinned in `packaging/runtime/fetch_runtimes.sh`.

The adjacent `python-build-standalone-20260623/` directory is an unmodified copy of every root `LICENSE*` file from the authoritative upstream tag. It covers the builder, CPython, and the native components identified by upstream, including BDB, bzip2, Expat, libedit, libffi, liblzma, libuuid, mpdecimal, ncurses, OpenSSL, SQLite, Tcl/Tk/Tix, zlib, and Linux X11/Xau/xcb components.

Source and exact license set: <https://github.com/astral-sh/python-build-standalone/tree/20260623>

The packaged runtime also retains CPython's own `lib/python3.13/LICENSE.txt` and installed Python packages' `*.dist-info/licenses/` directories. Platform archives differ, so package verification must confirm the selected runtime and its retained license files for each native target rather than treating one platform's contents as universal.
