"""Tests for tools/probe_subagent_stop.py.

The probe's whole purpose is to be trusted for one run against a live session,
so its two safety properties are the things worth testing hardest:

  - it stops blocking after N invocations, so it cannot wedge a session;
  - it never writes transcript text to the log unless explicitly asked, because
    a transcript can contain a secret and a log file is a second place to leak
    from (CLAUDE.md § Secrets).

A diagnostic that wedges the session, or that quietly copies credentials into
/tmp, is worse than the uncertainty it was built to resolve.
"""

import io
import json

import probe_subagent_stop as probe
import pytest

SECRET = "sk-live-DO-NOT-COPY-THIS-INTO-A-LOG"


def payload(**kwargs):
    return io.StringIO(json.dumps(kwargs))


def transcript(tmp_path, *messages, name="transcript.jsonl"):
    path = tmp_path / name
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "type": role,
                    "message": {
                        "role": role,
                        "content": [{"type": "text", "text": text}],
                    },
                }
            )
            for role, text in messages
        )
        + "\n"
    )
    return path


def run(tmp_path, argv=(), **payload_kwargs):
    log = tmp_path / "probe.log"
    code = probe.main_argv(["--log", str(log), *argv], stdin=payload(**payload_kwargs))
    return code, log


def read_records(log):
    """The log is pretty-printed JSON objects appended one after another."""
    text = log.read_text()
    decoder = json.JSONDecoder()
    records, idx = [], 0
    while idx < len(text):
        while idx < len(text) and text[idx] in " \n\t\r":
            idx += 1
        if idx >= len(text):
            break
        obj, end = decoder.raw_decode(text, idx)
        records.append(obj)
        idx = end
    return records


# --- it cannot wedge a session -----------------------------------------


def test_blocks_the_first_invocation(tmp_path):
    code, _ = run(tmp_path, ["--block", "1"], transcript_path="")
    assert code == probe.EXIT_BLOCK


def test_allows_the_second_invocation(tmp_path):
    """The property that makes this safe to point at a live session."""
    log = tmp_path / "probe.log"
    first = probe.main_argv(["--log", str(log), "--block", "1"], stdin=payload())
    second = probe.main_argv(["--log", str(log), "--block", "1"], stdin=payload())
    assert (first, second) == (probe.EXIT_BLOCK, probe.EXIT_OK)


def test_block_count_is_honoured(tmp_path):
    log = tmp_path / "probe.log"
    codes = [
        probe.main_argv(["--log", str(log), "--block", "3"], stdin=payload())
        for _ in range(5)
    ]
    assert codes == [probe.EXIT_BLOCK] * 3 + [probe.EXIT_OK] * 2


def test_block_zero_never_blocks(tmp_path):
    code, _ = run(tmp_path, ["--block", "0"])
    assert code == probe.EXIT_OK


def test_an_unreadable_counter_fails_toward_passing(tmp_path):
    """If the counter cannot be read, restarting at 1 must not mean blocking
    forever — the recovery path has to favour letting the session finish."""
    log = tmp_path / "probe.log"
    counter = log.with_suffix(".count")
    counter.write_text("not a number")
    assert probe.main_argv(["--log", str(log), "--block", "0"], stdin=payload()) == (
        probe.EXIT_OK
    )


def test_reset_clears_the_counter(tmp_path):
    log = tmp_path / "probe.log"
    probe.main_argv(["--log", str(log), "--block", "1"], stdin=payload())
    probe.main_argv(["--log", str(log), "--reset"])
    assert probe.main_argv(["--log", str(log), "--block", "1"], stdin=payload()) == (
        probe.EXIT_BLOCK
    )


# --- it does not leak transcript content -------------------------------


def test_transcript_text_is_never_logged_by_default(tmp_path):
    path = transcript(tmp_path, ("assistant", f"the token is {SECRET}"))
    log = tmp_path / "probe.log"
    probe.main_argv(
        ["--log", str(log), "--block", "0"], stdin=payload(transcript_path=str(path))
    )
    assert SECRET not in log.read_text()


def test_shape_is_recorded_without_the_text(tmp_path):
    path = transcript(
        tmp_path, ("user", "go"), ("assistant", f"secret {SECRET} here")
    )
    log = tmp_path / "probe.log"
    probe.main_argv(
        ["--log", str(log), "--block", "0"], stdin=payload(transcript_path=str(path))
    )
    shape = read_records(log)[0]["transcript"]
    assert shape["entries"] == 2
    assert shape["assistant_text_found_at_message_content_text"] is True
    assert shape["last_assistant_text_chars"] > 0
    assert "text" in shape["content_block_types"]
    assert SECRET not in json.dumps(shape)


def test_unsafe_dump_is_opt_in_and_does_include_text(tmp_path):
    """The escape hatch has to actually work, or someone will reach for
    something worse when they genuinely need to see the format."""
    path = transcript(tmp_path, ("assistant", "PLAIN MARKER TEXT"))
    log = tmp_path / "probe.log"
    probe.main_argv(
        ["--log", str(log), "--block", "0", "--unsafe-dump-tail"],
        stdin=payload(transcript_path=str(path)),
    )
    assert "PLAIN MARKER TEXT" in log.read_text()


# --- it records what the run is meant to answer ------------------------


def test_absent_keys_are_recorded_explicitly(tmp_path):
    """A missing field must be visible as ABSENT, not as silence — the whole
    point is learning which fields Claude Code actually sends."""
    log = tmp_path / "probe.log"
    probe.main_argv(
        ["--log", str(log), "--block", "0"], stdin=payload(agent_type="qa-tester")
    )
    interest = read_records(log)[0]["keys_of_interest"]
    assert interest["agent_type"] == "qa-tester"
    assert interest["stop_hook_active"] == "<ABSENT>"
    assert interest["transcript_path"] == "<ABSENT>"


def test_stop_hook_active_is_captured_when_present(tmp_path):
    log = tmp_path / "probe.log"
    probe.main_argv(
        ["--log", str(log), "--block", "0"], stdin=payload(stop_hook_active=True)
    )
    assert read_records(log)[0]["keys_of_interest"]["stop_hook_active"] is True


def test_each_invocation_appends_a_record(tmp_path):
    log = tmp_path / "probe.log"
    for _ in range(3):
        probe.main_argv(["--log", str(log), "--block", "0"], stdin=payload())
    records = read_records(log)
    assert [r["invocation"] for r in records] == [1, 2, 3]


def test_missing_transcript_file_is_recorded_not_fatal(tmp_path):
    log = tmp_path / "probe.log"
    code = probe.main_argv(
        ["--log", str(log), "--block", "0"],
        stdin=payload(transcript_path=str(tmp_path / "nope.jsonl")),
    )
    assert code == probe.EXIT_OK
    assert read_records(log)[0]["transcript"]["path_exists"] is False


def test_empty_stdin_still_records(tmp_path):
    """If nothing arrives on stdin that is itself the finding, and it has to
    reach the log rather than crashing the hook."""
    log = tmp_path / "probe.log"
    code = probe.main_argv(["--log", str(log), "--block", "0"], stdin=io.StringIO(""))
    assert code == probe.EXIT_OK
    record = read_records(log)[0]
    assert record["stdin_bytes"] == 0
    assert record["stdin_parsed_as_json"] is False


def test_block_message_names_the_marker_and_is_self_identifying(tmp_path, capsys):
    """The subagent sees this text if stderr is returned to it. It must be
    obviously a probe, or a subagent will treat it as a real QA finding."""
    probe.main_argv(["--log", str(tmp_path / "p.log"), "--block", "1"], stdin=payload())
    err = capsys.readouterr().err
    assert probe.MARKER in err
    assert "diagnostic hook, not a real finding" in err


@pytest.mark.parametrize("bad", ["not json", "{broken", "[]", "null"])
def test_unparseable_stdin_is_recorded_not_fatal(tmp_path, bad):
    log = tmp_path / "probe.log"
    code = probe.main_argv(
        ["--log", str(log), "--block", "0"], stdin=io.StringIO(bad)
    )
    assert code == probe.EXIT_OK
    assert read_records(log)[0]["payload_keys"] == []
