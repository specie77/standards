#!/usr/bin/env python3
"""Diagnostic SubagentStop hook: record what Claude Code actually sends, and
prove whether exit code 2 blocks a subagent from stopping.

Why this exists.

`docs/subagents.md` § "Mechanical claims — verification status" lists three
beliefs that `tools/qa_report_check.py` is built on and that nothing has ever
confirmed:

  1. a SubagentStop *command* hook exiting 2 blocks the stop, and its stderr is
     returned to the subagent;
  2. the payload carries `stop_hook_active`, so a blocked stop cannot loop;
  3. the transcript is JSONL with assistant text at `message.content[].text`.

They cannot be settled by reading documentation — none of it is documented.
They are settled by running one deliberately-failing hook once and looking at
what happened. This is that hook. Wire it, dispatch any trivial subagent task,
then read the log.

## Safety properties, both deliberate

**It cannot wedge your session.** `--block N` refuses the stop only for the
first N invocations and then passes, so the worst case is N extra turns, not a
subagent that can never finish. N defaults to 1.

**It does not write transcript content to disk.** The transcript carries
everything the subagent read, which on a QA run can include a secret it was
never supposed to surface (`CLAUDE.md` § Secrets: the transcript already
persists in Claude Code's session history; a second copy in a log file is a
second place to leak from). So this records the *shape* — which keys exist, how
many entries, which roles appear — and never the text. `--unsafe-dump-tail`
opts into recording the last message's first 400 characters when you need to
see the actual format; do not use it in a session that has touched real
credentials.

Stdlib only.

## Usage

Point a SubagentStop matcher at it in `.claude/settings.json`:

    "hooks": {
      "SubagentStop": [
        { "matcher": "qa-tester",
          "hooks": [{ "type": "command",
                      "command": "python3 ${CLAUDE_PROJECT_DIR}/.standards/tools/probe_subagent_stop.py --block 1" }] }
      ]
    }

Dispatch the subagent, then read the log (path is printed on every run, and
defaults to the system temp directory):

    cat "${TMPDIR:-/tmp}/subagent-stop-probe.log"

Restore the real `qa_report_check.py` matcher afterwards. See
`docs/subagent-deployment.md` § "Verify the referee" for the full scenario and
how to read the result.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EXIT_BLOCK = 2
EXIT_OK = 0

MARKER = "SUBAGENT-STOP-PROBE"

# Payload keys this design depends on. Recorded present/absent explicitly so a
# missing one is visible in the log rather than inferred from silence.
KEYS_OF_INTEREST = (
    "hook_event_name",
    "session_id",
    "transcript_path",
    "cwd",
    "agent_type",
    "agent_id",
    "permission_mode",
    "stop_hook_active",
)


def transcript_shape(path: Path, dump_tail: bool) -> dict:
    """Structural facts about the transcript. No message text unless asked."""
    shape: dict = {"path_exists": path.exists()}
    if not path.exists():
        return shape

    entries = 0
    malformed = 0
    roles: dict[str, int] = {}
    top_level_keys: set[str] = set()
    message_keys: set[str] = set()
    content_block_types: set[str] = set()
    last_assistant_text = None

    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                entries += 1
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(entry, dict):
                    malformed += 1
                    continue
                top_level_keys.update(entry.keys())
                message = entry.get("message")
                message = message if isinstance(message, dict) else entry
                if isinstance(message, dict):
                    message_keys.update(message.keys())
                role = message.get("role") or entry.get("type")
                roles[str(role)] = roles.get(str(role), 0) + 1
                content = message.get("content")
                if isinstance(content, str):
                    content_block_types.add("<bare string>")
                    if role == "assistant" and content.strip():
                        last_assistant_text = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            content_block_types.add(str(block.get("type")))
                            if (
                                role == "assistant"
                                and block.get("type") == "text"
                                and isinstance(block.get("text"), str)
                                and block["text"].strip()
                            ):
                                last_assistant_text = block["text"]
                        else:
                            content_block_types.add(type(block).__name__)
    except OSError as exc:
        shape["read_error"] = str(exc)
        return shape

    shape.update(
        {
            "entries": entries,
            "malformed_lines": malformed,
            "roles_seen": roles,
            "entry_keys": sorted(top_level_keys),
            "message_keys": sorted(message_keys),
            "content_block_types": sorted(content_block_types),
            # The question qa_report_check.py actually depends on.
            "assistant_text_found_at_message_content_text": last_assistant_text
            is not None,
            "last_assistant_text_chars": (
                len(last_assistant_text) if last_assistant_text else 0
            ),
        }
    )
    if dump_tail and last_assistant_text:
        shape["UNSAFE_last_assistant_text_head"] = last_assistant_text[:400]
    return shape


def next_invocation(counter: Path) -> int:
    """1 for the first call, 2 for the second, and so on. Best effort: an
    unreadable counter restarts at 1, which fails toward passing rather than
    toward blocking forever."""
    try:
        seen = int(counter.read_text().strip())
    except (OSError, ValueError):
        seen = 0
    seen += 1
    try:
        counter.write_text(str(seen))
    except OSError:
        pass
    return seen


def main_argv(argv: list[str] | None = None, stdin=None) -> int:
    default_log = Path(tempfile.gettempdir()) / "subagent-stop-probe.log"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--block",
        type=int,
        default=1,
        metavar="N",
        help="refuse the stop for the first N invocations, then allow it "
        "(default: 1). 0 never blocks — records only.",
    )
    parser.add_argument(
        "--log", type=Path, default=default_log, help=f"default: {default_log}"
    )
    parser.add_argument(
        "--reset", action="store_true", help="clear the log and the counter, then exit"
    )
    parser.add_argument(
        "--unsafe-dump-tail",
        action="store_true",
        help="also record the last assistant message's first 400 characters. "
        "Transcript text can contain secrets — do not use on a real session.",
    )
    args = parser.parse_args(argv)

    counter = args.log.with_suffix(".count")

    if args.reset:
        for path in (args.log, counter):
            try:
                path.unlink()
            except OSError:
                pass
        print(f"{MARKER}: reset {args.log} and {counter}")
        return EXIT_OK

    raw = ""
    try:
        raw = (stdin if stdin is not None else sys.stdin).read()
    except OSError:
        pass
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    invocation = next_invocation(counter)
    will_block = args.block > 0 and invocation <= args.block

    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "invocation": invocation,
        "pid": os.getpid(),
        "stdin_bytes": len(raw),
        "stdin_parsed_as_json": bool(raw.strip()) and payload != {},
        "payload_keys": sorted(payload.keys()),
        "keys_of_interest": {
            key: (payload[key] if key in payload else "<ABSENT>")
            for key in KEYS_OF_INTEREST
        },
        "transcript": transcript_shape(
            Path(str(payload.get("transcript_path", ""))), args.unsafe_dump_tail
        )
        if payload.get("transcript_path")
        else {"transcript_path": "<ABSENT>"},
        "action": "BLOCK (exit 2)" if will_block else "ALLOW (exit 0)",
    }

    try:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, indent=2, default=str) + "\n")
    except OSError as exc:
        print(f"{MARKER}: could not write {args.log}: {exc}", file=sys.stderr)

    if will_block:
        print(
            f"{MARKER}: refusing this stop deliberately (invocation "
            f"{invocation} of {args.block}). This is a diagnostic hook, not a "
            f"real finding. If you are the subagent reading this: add the line "
            f"'{MARKER} acknowledged' to your final report and stop again. "
            f"Log: {args.log}",
            file=sys.stderr,
        )
        return EXIT_BLOCK

    print(f"{MARKER}: allowed (invocation {invocation}). Log: {args.log}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main_argv())
