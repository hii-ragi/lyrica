"""One JSON request on stdin, one JSON response on stdout; progress goes to stderr."""
import contextlib
import json
import sys

from lyrica_backend.lrc import render_lrc


def progress(stage, message, completed=None, total=None):
    event = {"stage": stage, "message": message}
    if completed is not None and total is not None:
        event.update(completed=completed, total=total)
    print("LYRICA_EVENT " + json.dumps(event, ensure_ascii=False),
          file=sys.stderr, flush=True)


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    # Do not pass PyInstaller's DLL directory to the managed Python/uv executables.
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("unsupported operation")
        operation = request.get("operation")
        with contextlib.redirect_stdout(sys.stderr):
            if operation == "render_lrc":
                response = {"lrc": render_lrc(request.get("lines"))}
            elif operation == "export_batch":
                from lyrica_backend.export import export_batch
                response = export_batch(request["directory"], request["tracks"], request.get("format", "lrc"))
            elif operation == "runtime_status":
                from lyrica_backend.runtime import runtime_status
                response = runtime_status(request["runtime_dir"], request["resource_dir"], request.get("device","cpu"))
            elif operation == "setup_runtime":
                from lyrica_backend.runtime import setup_runtime
                response = setup_runtime(request["runtime_dir"], request["resource_dir"],
                                         request["uv_path"], progress, request.get("device","cpu"))
            elif operation in ("readings", "analyze"):
                from lyrica_backend.runtime import run_worker
                response = run_worker(request, request["runtime_dir"], request["resource_dir"])
            else:
                raise ValueError("unsupported operation")
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
