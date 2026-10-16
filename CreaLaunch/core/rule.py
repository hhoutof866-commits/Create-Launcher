"""Правила версий (os / features) и подстановка переменных в аргументы."""

from __future__ import annotations

from .paths import platform_arch, platform_name


def default_features():
    return {
        "is_demo_user": False,
        "has_custom_resolution": False,
        "has_quick_plays_support": False,
        "is_quick_play_singleplayer": False,
        "is_quick_play_multiplayer": False,
        "is_quick_play_realms": False,
    }


def _os_rule_ok(rule_os: dict) -> bool:
    if not rule_os:
        return True
    name = rule_os.get("name")
    if name and name != platform_name():
        return False
    arch = rule_os.get("arch")
    if arch and arch != platform_arch():
        return False
    # version/regex — на практике не встречается в актуальных версиях
    if rule_os.get("version") and platform_name() != "windows":
        return False
    return True


def rules_allow(rules, features=None) -> bool:
    """Правила Mojang: идём по списку, последнее подходящее правило решает."""
    if rules is None:
        return True
    feats = features or default_features()
    allowed = False
    for rule in rules:
        ok = True
        if "os" in rule and not _os_rule_ok(rule.get("os") or {}):
            ok = False
        if ok and "features" in rule:
            for key, want in (rule.get("features") or {}).items():
                if bool(feats.get(key, False)) != bool(want):
                    ok = False
                    break
        if ok:
            allowed = rule.get("action", "allow") == "allow"
    return allowed


def substitute(text: str, mapping: dict) -> str:
    if "${" not in text:
        return text
    out = text
    for key, value in mapping.items():
        token = "${%s}" % key
        if token in out:
            out = out.replace(token, str(value))
    return out


def resolve_arguments(elements, mapping: dict, features=None):
    """Разворачивает arguments.jvm / arguments.game в плоский список строк."""
    result = []
    for element in elements or []:
        if isinstance(element, str):
            result.append(substitute(element, mapping))
            continue
        if rules_allow(element.get("rules"), features):
            value = element.get("value", [])
            if isinstance(value, str):
                value = [value]
            for item in value:
                result.append(substitute(item, mapping))
    # незаполненные переменные (quickPlay и т.п.) выбрасываем вместе с ключом
    cleaned = []
    skip_next = False
    for token in result:
        if skip_next:
            skip_next = False
            continue
        if "${" in token:
            skip_next = token.startswith("--")
            continue
        cleaned.append(token)
    return cleaned
