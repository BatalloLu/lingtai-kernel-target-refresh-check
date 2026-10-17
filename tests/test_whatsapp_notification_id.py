"""Thin filesystem regression for the normal WhatsApp -> canonical LICC seam."""
from __future__ import annotations

import json
import logging
import re
from unittest.mock import Mock

from lingtai.mcp_servers.whatsapp import manager as whatsapp


def test_inbound_notification_ids_are_stable_distinct_and_admissible(tmp_path, monkeypatch):
    # Delimiter ambiguity, lossy sanitization, and truncation must not alias.
    tuples = [
        ("sender", "a:b"), ("sender:a", "b"),
        ("sender", "a/b"), ("sender", "a_b"),
        ("sender", "x" * 130 + "a"), ("sender", "x" * 130 + "b"),
        ("sender", "a:b"),
    ]
    stems = []
    monkeypatch.setenv("LINGTAI_MCP_NAME", "whatsapp")
    for index, (sender, message_id) in enumerate(tuples):
        workdir = tmp_path / str(index)
        monkeypatch.setenv("LINGTAI_AGENT_DIR", str(workdir))
        manager = whatsapp.WhatsAppManager({"autostart": False}, working_dir=workdir)
        message = {"from": sender, "id": message_id, "body": "hello", "type": "text"}
        manager._on_bridge_event({"type": "message", "data": message})
        events = list((workdir / ".mcp_inbox" / "whatsapp").glob("*.json"))
        assert len(events) == 1
        event = json.loads(events[0].read_text(encoding="utf-8"))
        assert re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", events[0].stem)
        assert event["wake"] is True
        assert event["metadata"]["message_id"] == message_id
        assert event["metadata"]["latest_incoming"]["text"] == "hello"
        assert "hello" in event["body"]
        archive = manager._message_path(sender, "inbox", message_id)
        seen = manager.store_dir / "inbox_seen.json"
        before = (archive.read_bytes(), seen.read_bytes(), events[0].read_bytes())
        manager._on_bridge_event({"type": "message", "data": message})
        assert (archive.read_bytes(), seen.read_bytes(), events[0].read_bytes()) == before
        stems.append(events[0].stem)
    assert len(set(stems[:-1])) == len(tuples) - 1
    assert stems[0] == stems[-1]


def test_publication_failure_warns_without_retry_or_seen_repair(tmp_path, monkeypatch, caplog):
    publish = Mock(return_value=False)
    monkeypatch.setattr(whatsapp, "push_inbox_event", publish)
    manager = whatsapp.WhatsAppManager({"autostart": False}, working_dir=tmp_path)
    message = {"from": "private-sender", "id": "private-id", "body": "private-body"}
    with caplog.at_level(logging.WARNING, logger=whatsapp.__name__):
        manager._handle_incoming(message)
        manager._handle_incoming(message)
    assert publish.call_count == 1
    assert manager._message_path(message["from"], "inbox", message["id"]).is_file()
    assert manager._is_replay(manager._stable_key(message["from"], message))
    assert "inbound LICC notification publication failed" in caplog.text
    assert all(value not in caplog.text for value in message.values())
