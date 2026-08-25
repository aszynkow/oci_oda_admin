"""Declarative OCI Admin skill specification and local simulator."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Match:
    intent: str
    answer: str
    confidence: float


def load_spec(path: Path) -> dict[str, Any]:
    """Read the single YAML file that defines a skill, assistant, and channel."""
    content = yaml.safe_load(path.read_text())
    if not isinstance(content, dict):
        raise TypeError("The specification must contain a YAML mapping.")
    return content


def validate_spec(spec: dict[str, Any]) -> list[str]:
    """Return human-readable validation errors without contacting OCI."""
    errors: list[str] = []
    skill = spec.get("skill", {})
    if not skill.get("name"):
        errors.append("skill.name is required")
    intents = skill.get("intents", [])
    if not isinstance(intents, list) or not intents:
        errors.append("skill.intents must contain at least one intent")
        return errors
    names: set[str] = set()
    for intent in intents:
        name = intent.get("name") if isinstance(intent, dict) else None
        if not name:
            errors.append("each intent needs a name")
            continue
        if name in names:
            errors.append(f"duplicate intent: {name}")
        names.add(name)
        if not intent.get("utterances"):
            errors.append(f"{name}: add at least one utterance")
        flow = intent.get("flow", {})
        if not isinstance(flow, dict) or not flow.get("steps"):
            errors.append(f"{name}: flow.steps is required")
        elif flow["steps"][0].get("type") != "send_message":
            errors.append(f"{name}: first flow step must be send_message")
    assistant = spec.get("assistant", {})
    if not assistant.get("name"):
        errors.append("assistant.name is required")
    if assistant.get("skill") != skill.get("name"):
        errors.append("assistant.skill must match skill.name")
    return errors


def deployment_plan(spec: dict[str, Any]) -> dict[str, Any]:
    """Compile YAML to portable JSON ready for an ODA REST adapter."""
    skill = spec["skill"]
    intents = skill["intents"]
    flows = [
        {"name": item["name"], "intent": item["name"], "steps": item["flow"]["steps"]}
        for item in intents
    ]
    return {
        "api_version": 1,
        "skill": {
            "name": skill["name"],
            "version": str(skill["version"]),
            "platform_version": str(skill.get("platform_version", "26.04")),
            "description": skill.get("description", ""),
            "invocation": skill.get("invocation", skill["name"]),
            "intents": [
                {
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "utterances": item["utterances"],
                    "answer": item["flow"]["steps"][0]["text"],
                }
                for item in intents
            ],
            "flows": flows,
        },
        "assistant": spec["assistant"],
        "channel": spec.get("channel", {}),
        "lifecycle": ["validate", "train", "publish_skill", "publish_assistant", "route_channel"],
    }


def local_match(spec: dict[str, Any], message: str) -> Match | None:
    """Small offline simulator based on the configured example utterances."""
    terms = set(re.findall(r"[a-z0-9]+", message.lower()))
    best: Match | None = None
    for intent in spec["skill"]["intents"]:
        examples = intent.get("utterances", [])
        for example in examples:
            example_terms = set(re.findall(r"[a-z0-9]+", example.lower()))
            score = len(terms & example_terms) / max(len(terms | example_terms), 1)
            if best is None or score > best.confidence:
                answer = intent["flow"]["steps"][0]["text"]
                best = Match(intent["name"], answer, score)
    return best if best and best.confidence > 0 else None


def runtime_checks(spec: dict[str, Any]) -> list[dict[str, str]]:
    """Detect mapped visual flows that would fail at runtime."""
    checks: list[dict[str, str]] = []
    for intent in spec.get("skill", {}).get("intents", []):
        name = intent.get("name", "<unnamed>")
        steps = intent.get("flow", {}).get("steps", [])
        if not steps:
            checks.append({"intent": name, "status": "failed", "reason": "flow has no states"})
        elif not any(step.get("type") == "send_message" for step in steps):
            checks.append({"intent": name, "status": "failed", "reason": "flow has no send_message state"})
        elif steps[-1].get("type") != "end_flow":
            checks.append({"intent": name, "status": "failed", "reason": "flow does not end"})
        else:
            checks.append({"intent": name, "status": "passed", "reason": "send_message and end_flow defined"})
    return checks


def local_test_suite(spec: dict[str, Any]) -> list[dict[str, str]]:
    """Run every configured utterance through the offline matcher."""
    results: list[dict[str, str]] = []
    for intent in spec["skill"]["intents"]:
        for utterance in intent["utterances"]:
            match = local_match(spec, utterance)
            actual = match.intent if match else ""
            results.append({"utterance": utterance, "expected_intent": intent["name"], "actual_intent": actual, "status": "passed" if actual == intent["name"] else "failed"})
    return results
