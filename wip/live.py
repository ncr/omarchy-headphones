#!/usr/bin/env python3
"""Drive the real bose-bridge against the headset and restore it after.

Usage: live.py <bridge-path> <address>
"""
import json
import signal
import subprocess
import sys
import threading
import time

lines = []
lock = threading.Lock()


def reader(proc):
    for raw in proc.stdout:
        raw = raw.strip()
        if not raw:
            continue
        print("   <- %s" % raw, flush=True)
        try:
            with lock:
                lines.append(json.loads(raw))
        except ValueError:
            pass


def wait_for(predicate, seconds, what):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with lock:
            last = lines[-1] if lines else None
        if last and predicate(last):
            print("   OK  %s" % what, flush=True)
            return last
        time.sleep(0.1)
    with lock:
        last = lines[-1] if lines else None
    print("   !!  TIMEOUT waiting for %s (last: %s)" % (what, last), flush=True)
    return None


def main():
    bridge, address = sys.argv[1], sys.argv[2]
    proc = subprocess.Popen([bridge, address], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, bufsize=1)
    threading.Thread(target=reader, args=(proc,), daemon=True).start()

    def say(command):
        print("\n>> %s" % command, flush=True)
        proc.stdin.write(command + "\n")
        proc.stdin.flush()

    initial = None
    try:
        print("\n== first reading ==", flush=True)
        first = wait_for(lambda l: l.get("modes") is True, 30, "a live line")
        if first is None:
            return 1
        initial = (first.get("mode"), first.get("ancLevel"))
        print("   initial = %s" % (initial,), flush=True)

        say("set off")
        wait_for(lambda l: l.get("mode") == "off", 15, "mode off")

        say("set anc")
        wait_for(lambda l: l.get("mode") == "anc", 15, "mode anc")

        say("level low")
        wait_for(lambda l: l.get("mode") == "anc" and l.get("ancLevel") == "low",
                 15, "anc at low")

        say("level high")
        wait_for(lambda l: l.get("mode") == "anc" and l.get("ancLevel") == "high",
                 15, "anc at high")

        say("set ambient")
        say("set talkthru")
        say("level mid")
        say("voice on")
        say("latency on")
        time.sleep(6)
        with lock:
            last = lines[-1]
        print("   after the five unsupported commands: %s" % last, flush=True)
    finally:
        if initial is not None:
            mode, level = initial
            print("\n== restoring %s / %s ==" % (mode, level), flush=True)
            if mode == "off":
                say("set off")
                wait_for(lambda l: l.get("mode") == "off", 15, "restored off")
            else:
                say("level %s" % level)
                wait_for(lambda l: l.get("mode") == "anc"
                         and l.get("ancLevel") == level, 15,
                         "restored anc at %s" % level)
        proc.send_signal(signal.SIGTERM)
        try:
            code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = "killed"
        print("\n== bridge exit code: %s ==" % code, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
