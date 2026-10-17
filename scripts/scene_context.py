"""Position-scoped, human-maintained continuity evidence. No model or writes.

Plans and model candidates are never promoted by this module. A hash proves
which bytes were reviewed, not that a human's factual interpretation is true.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

LEDGER = "continuity-ledger.json"
CONTRACT = (
    "current_plan 是当前场设计，不是已发生事实。accepted_facts 仅是此前人工验收且来源未变的状态。"
    "不要把计划、猜测、candidate 或本次生成自动当成已验收事实；不得提前揭示未来信息。"
    "未列事实代表未知，不代表可自行恢复旧状态。输出正文不能更新或批准账本。"
)


class ContextError(ValueError):
    """Invalid or stale opt-in continuity evidence; do not silently fall back."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _inside(story: Path, path: Path) -> Path:
    if not path.resolve().is_relative_to(story.resolve()):
        raise ContextError("continuity input escapes story directory")
    return path


def scene_order(story: Path) -> list[str]:
    cards = []
    seen = set()
    for path in _inside(story, story / "scene-cards").glob("scene-*.json"):
        _inside(story, path)
        card = json.loads(path.read_text(encoding="utf-8"))
        sid = card.get("scene_id")
        if not isinstance(sid, str) or not re.fullmatch(r"scene-[0-9]+", sid) or path.stem != sid:
            raise ContextError("scene card must have a matching scene-N numeric ID")
        number = int(sid.split("-")[1])
        if number in seen:
            raise ContextError("ambiguous numeric scene order")
        seen.add(number)
        cards.append((number, sid))
    if not cards:
        raise ContextError("continuity requires scene cards")
    return [sid for _, sid in sorted(cards)]


def source_evidence(story: Path, sid: str) -> dict[str, str]:
    """Read-only evidence for a human to copy into an accepted entry.

    Includes all predecessor drafts (including missing markers). This binds a
    later interpretation to its earlier text, without trusting file mtimes.
    """
    order = scene_order(story)
    if sid not in order:
        raise ContextError("unknown source scene")
    prefix = {}
    for earlier in order[:order.index(sid) + 1]:
        path = _inside(story, story / "draft-scenes" / f"{earlier}.md")
        prefix[earlier] = digest(path.read_bytes()) if path.is_file() else None
    if prefix[sid] is None:
        raise ContextError(f"missing source draft: {sid}")
    return {"scene_id": sid, "sha256": prefix[sid], "prefix_sha256": digest(encoded(prefix).encode())}


def build_context(story: Path, sid: str, *, max_chars: int = 16000) -> dict[str, Any]:
    """Rebuild on every use; never reuse a stale saved projection.

    max_chars bounds the serialized context including its audit report. Hard
    facts and current plan are indivisible; only the excerpt may be trimmed.
    """
    order = scene_order(story)
    if sid not in order:
        raise ContextError("unknown target scene")
    target = order.index(sid)
    card_path = _inside(story, story / "scene-cards" / f"{sid}.json")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    ledger_path = _inside(story, story / LEDGER)
    context: dict[str, Any] = {
        "schema_version": 1, "scene_id": sid, "contract": CONTRACT,
        "context_sha256": "0" * 64,
        "current_plan": card, "accepted_facts": [], "open_debts": [],
        "recent_excerpt": "", "warnings": [],
        "budget": {"max_chars": max_chars, "excerpt_original_chars": 0, "excerpt_kept_chars": 0,
                   "trimmed": [], "hard_facts_dropped": 0},
    }
    if not ledger_path.exists():
        context["warnings"].append("No ledger: no structured continuity guarantees; plans are not accepted facts.")
    else:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if not isinstance(ledger, dict) or ledger.get("schema_version") != 1 or not isinstance(ledger.get("entries"), list):
            raise ContextError("invalid continuity ledger schema")
        states = {}
        ids = set()
        evidence_cache = {}
        recent = None
        for entry in ledger["entries"]:
            if not isinstance(entry, dict) or entry.get("status") not in {"accepted", "candidate", "rejected"}:
                raise ContextError("each ledger entry needs an explicit status")
            if entry["status"] != "accepted":
                continue
            for field in ("id", "entity_id", "field", "reviewed_by", "valid_from_scene"):
                if not isinstance(entry.get(field), str) or not entry[field].strip():
                    raise ContextError(f"accepted entry requires {field}")
            if entry["id"] in ids:
                raise ContextError("duplicate accepted entry ID")
            ids.add(entry["id"])
            source = entry.get("source")
            if not isinstance(source, dict) or source.get("scene_id") not in order:
                raise ContextError("accepted entry requires an in-story source scene")
            source_index = order.index(source["scene_id"])
            if entry["valid_from_scene"] not in order:
                raise ContextError("unknown effective scene")
            effective = order.index(entry["valid_from_scene"])
            if effective < source_index:
                raise ContextError("fact cannot take effect before its source")
            if "value" not in entry or entry.get("kind", "state") not in {"state", "debt"}:
                raise ContextError("accepted entry requires a value and valid kind")
            if source_index >= target or effective > target:
                continue  # Never render future values, quotes, IDs, or counts.
            source_id = source["scene_id"]
            if source_id not in evidence_cache:
                evidence_cache[source_id] = source_evidence(story, source_id)
            if any(source.get(key) != value for key, value in evidence_cache[source_id].items()):
                raise ContextError(f"stale continuity evidence at {source_id}; review against current drafts")
            text = _inside(story, story / "draft-scenes" / f"{source_id}.md").read_text(encoding="utf-8")
            if not isinstance(source.get("quote"), str) or not source["quote"] or source["quote"] not in text:
                raise ContextError(f"source quote missing at {source_id}")
            key = (entry.get("kind", "state"), entry["entity_id"], entry["field"])
            rank = (effective, source_index)
            if key in states and states[key][0] == rank:
                raise ContextError("ambiguous same-position accepted states")
            if key not in states or states[key][0] < rank:
                # Whitelist fields: notes/extraction guesses are not factual context.
                projected = {k: entry[k] for k in (
                    "id", "entity_id", "field", "value", "valid_from_scene", "reviewed_by"
                )}
                projected["source"] = {key: source[key] for key in ("scene_id", "sha256", "prefix_sha256", "quote")}
                states[key] = (rank, projected)
            if recent is None or recent[0] < source_index:
                recent = (source_index, text)
        for key, (_, fact) in sorted(states.items()):
            if key[0] == "debt":
                # Debt value must explicitly encode open/resolved; no model inference.
                if not isinstance(fact["value"], dict) or fact["value"].get("status") not in {"open", "resolved"}:
                    raise ContextError("debt value needs open/resolved status")
                if fact["value"]["status"] == "open":
                    context["open_debts"].append(fact)
            context["accepted_facts"].append(fact)
        if recent:
            context["recent_excerpt"] = recent[1]
    excerpt = context["recent_excerpt"]
    budget = context["budget"]
    budget["excerpt_original_chars"] = len(excerpt)
    budget["excerpt_kept_chars"] = len(excerpt)
    if len(encoded(context)) > max_chars:
        context["recent_excerpt"] = ""
        budget["excerpt_kept_chars"] = 0
        if excerpt:
            budget["trimmed"] = ["recent_excerpt: character budget; hard facts and current plan retained"]
        if len(encoded(context)) > max_chars:
            raise ContextError("continuity budget too small for current plan and accepted facts; increase max_chars or review ledger")
        # Keep a contiguous tail; binary search includes JSON escaping/report cost.
        low, high = 0, len(excerpt)
        while low < high:
            mid = (low + high + 1) // 2
            context["recent_excerpt"] = excerpt[-mid:]
            budget["excerpt_kept_chars"] = mid
            if len(encoded(context)) <= max_chars:
                low = mid
            else:
                high = mid - 1
        context["recent_excerpt"] = excerpt[-low:] if low else ""
        budget["excerpt_kept_chars"] = low
    context["context_sha256"] = digest(encoded({k: v for k, v in context.items() if k != "context_sha256"}).encode())
    return context


def context_for_batch(story: Path, batch: list[Path], *, max_chars: int = 16000) -> str:
    """Only opt-in stories change the historical batch prompt."""
    if not (story / LEDGER).exists():
        return "No continuity ledger: scene cards are plans, not accepted facts."
    if len(batch) != 1:
        raise ContextError("continuity ledger requires one scene per prompt to isolate future information")
    card = json.loads(_inside(story, batch[0]).read_text(encoding="utf-8"))
    if batch[0].resolve() != (story / "scene-cards" / f"{card.get('scene_id')}.json").resolve():
        raise ContextError("batch card must match the in-story scene card")
    return encoded(build_context(story, card["scene_id"], max_chars=max_chars))
