"""Entrega multi-alvo de cron (paridade Hermes): `--to "123,456"` manda o mesmo resultado pros dois
chats; sem alvo → home (/sethome); vazio sem home → ninguém (só registro)."""

from __future__ import annotations

from okami.automation.scheduler import delivery_targets


def test_single_target():
    assert delivery_targets("123", home="") == ["123"]


def test_multi_targets_comma():
    assert delivery_targets("123, 456 ,789", home="") == ["123", "456", "789"]


def test_no_target_falls_back_to_home():
    assert delivery_targets(None, home="777") == ["777"]
    assert delivery_targets("", home="777") == ["777"]


def test_no_target_no_home_is_empty():
    assert delivery_targets(None, home="") == []


def test_dedup_targets():
    assert delivery_targets("9,9,9", home="") == ["9"]
