from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    from google import genai
    from google.genai import types as genai_types
except Exception:  # pragma: no cover
    genai = None  # type: ignore
    genai_types = None  # type: ignore


@dataclass
class SummaryResult:
    summary_id: str
    summary_text: str
    decisions: list[str]
    actions: list[str]
    risks: list[str]
    model: str
    fallback_used: bool


class SummarizerService:
    def __init__(self, model: str, timeout_seconds: int, gemini_api_key: str | None = None) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.gemini_api_key = gemini_api_key
        self._client = None
        if gemini_api_key and genai:
            self._client = genai.Client(api_key=gemini_api_key)

    def _build_transcript(self, messages: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for message in messages:
            ts = message.get("created_at")
            if isinstance(ts, datetime):
                ts_text = ts.isoformat(timespec="seconds")
            else:
                ts_text = str(ts)
            author = str(message.get("author", "unknown"))
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            lines.append(f"[{ts_text}] {author}: {content}")
        return "\n".join(lines)

    def _fallback_extract(self, messages: list[dict[str, Any]]) -> SummaryResult:
        decision_keys = ["결정", "결론", "확정", "하기로", "결정:"]
        action_keys = ["todo", "할 일", "action", "담당", "까지"]
        risk_keys = ["리스크", "위험", "문제", "이슈", "blocker", "막힘"]

        decisions: list[str] = []
        actions: list[str] = []
        risks: list[str] = []

        for message in messages:
            text = str(message.get("content", "")).strip()
            if not text:
                continue
            lower = text.lower()
            if any(k.lower() in lower for k in decision_keys):
                decisions.append(text)
            if any(k.lower() in lower for k in action_keys):
                actions.append(text)
            if any(k.lower() in lower for k in risk_keys):
                risks.append(text)

        summary_text = "대화 핵심을 룰 기반으로 요약했습니다. 모델 요약을 사용할 수 없는 상태입니다."
        return SummaryResult(
            summary_id=str(uuid.uuid4()),
            summary_text=summary_text,
            decisions=decisions[:8],
            actions=actions[:8],
            risks=risks[:8],
            model="rule-fallback",
            fallback_used=True,
        )

    def _parse_json_block(self, text: str) -> dict[str, Any] | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def summarize(self, messages: list[dict[str, Any]], scope_label: str) -> SummaryResult:
        if not messages:
            return SummaryResult(
                summary_id=str(uuid.uuid4()),
                summary_text="요약할 메시지가 없습니다.",
                decisions=[],
                actions=[],
                risks=[],
                model=self.model,
                fallback_used=False,
            )

        if not self._client:
            return self._fallback_extract(messages)

        transcript = self._build_transcript(messages)
        prompt = (
            "다음 회의 대화를 JSON으로 요약하세요. "
            "반드시 키를 summary, decisions, actions, risks 로 반환하세요. "
            "각 배열은 한국어 문자열 목록으로 작성하세요.\n\n"
            f"Scope: {scope_label}\n"
            f"Transcript:\n{transcript}"
        )

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=900,
                    response_mime_type="application/json",
                ),
            )
            output_text = str(getattr(response, "text", "") or "")
            parsed = self._parse_json_block(output_text)
            if not parsed:
                return self._fallback_extract(messages)
            summary_raw = parsed.get("summary", "")
            if isinstance(summary_raw, list):
                summary_raw = " / ".join(str(x) for x in summary_raw if x is not None)
            summary_text = str(summary_raw) if summary_raw else "요약 결과가 비어 있습니다."
            decisions_raw = parsed.get("decisions")
            if not decisions_raw:
                decisions_raw = parsed.get("todos") or []
            actions_raw = parsed.get("actions")
            if not actions_raw:
                actions_raw = parsed.get("todo") or []
            return SummaryResult(
                summary_id=str(uuid.uuid4()),
                summary_text=summary_text,
                decisions=[str(x) for x in decisions_raw][:12],
                actions=[str(x) for x in actions_raw][:12],
                risks=[str(x) for x in parsed.get("risks", [])][:12],
                model=self.model,
                fallback_used=False,
            )
        except Exception:
            return self._fallback_extract(messages)
