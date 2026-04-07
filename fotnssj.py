# ════════════════════════════════════════════════════════════════════════
# FOTNSSJ — Complete Integrated System
# ════════════════════════════════════════════════════════════════════════
# Includes:
# - Core FOTNSSJ Checkpoint & Geometry Layer
# - Raw Session Event Store (Layer 2)
# - Dynamic LLM Question Generator & Cache
# - NFC Physical Station Registry
# - Teacher & Admin Auth Portals
# - Complete Flask Web Interface
# ════════════════════════════════════════════════════════════════════════

import os
import re
import time
import json
import uuid
import math
import queue
import hashlib
import hmac
import secrets
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from flask import (
    Flask, request, session, redirect,
    url_for, jsonify, render_template_string, Response
)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("[!] 'openai' package not found. Falling back to hardcoded questions.")

from dispatch import OllamaDispatcher, Priority
from geometry.manifest import GeometryManifest


def _parse_questions(raw: str) -> Optional[List[Dict]]:
    """Parse a JSON array of question dicts from raw LLM output."""
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(raw[start:end + 1])
        valid = [
            i for i in data
            if isinstance(i, dict)
            and {"question", "correct_answer", "explanation", "bridge"}.issubset(i.keys())
        ]
        return valid if valid else None
    except json.JSONDecodeError:
        return None

def _answers_match(student_answer: str, correct_answer: str) -> bool:
    """
    Language-aware answer comparison.
    Handles accents, full-width characters, Arabic diacritics,
    extra whitespace, and case differences.
    """
    def normalise(text: str) -> str:
        # Lowercase
        text = text.lower().strip()
        # Unicode NFC normalisation — combines accent characters
        text = unicodedata.normalize("NFC", text)
        # Remove Arabic diacritics (tashkeel) — students often omit them
        text = re.sub(r"[\u0610-\u061A\u064B-\u065F]", "", text)
        # Collapse internal whitespace
        text = re.sub(r"\s+", " ", text)
        # Convert full-width digits/letters to ASCII (Japanese/Chinese input)
        text = text.translate(str.maketrans(
            "０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
            "0123456789abcdefghijklmnopqrstuvwxyz"
        ))
        # Convert written numbers to digits for math questions
        number_words = {
            "zero":"0","one":"1","two":"2","three":"3","four":"4",
            "five":"5","six":"6","seven":"7","eight":"8","nine":"9","ten":"10",
            "cuatro":"4","quatre":"4","vier":"4","quattro":"4",
            "cinco":"5","cinq":"5","fünf":"5",
        }
        for word, digit in number_words.items():
            text = re.sub(r"\b" + word + r"\b", digit, text)
        return text

    return normalise(student_answer) == normalise(correct_answer)

# ════════════════════════════════════════════════════════════════════════
# §1 CORE GEOMETRY & CHECKPOINT DATA STRUCTURES
# ════════════════════════════════════════════════════════════════════════

@dataclass
class TiltVector:
    alpha_delta: float
    cave_delta: float
    L_net_delta: float

    @property
    def magnitude(self) -> float:
        return math.sqrt(self.alpha_delta**2 + self.cave_delta**2 + self.L_net_delta**2)

    @property
    def dominant_dimension(self) -> str:
        dims = {"alpha": abs(self.alpha_delta), "cave": abs(self.cave_delta), "L_net": abs(self.L_net_delta)}
        return max(dims, key=dims.get)

    def to_dict(self) -> Dict:
        return {"alpha_delta": self.alpha_delta, "cave_delta": self.cave_delta, "L_net_delta": self.L_net_delta}

    @classmethod
    def from_dict(cls, d: Dict) -> "TiltVector":
        return cls(**d)

@dataclass
class GeometricPosition:
    alpha: float
    cave_depth: float
    L_net: float

    def to_dict(self) -> Dict:
        return {"alpha": self.alpha, "cave_depth": self.cave_depth, "L_net": self.L_net}

    @classmethod
    def from_dict(cls, d: Dict) -> "GeometricPosition":
        return cls(**d)

    @classmethod
    def default(cls) -> "GeometricPosition":
        return cls(1.0, 0.5, 0.5)

@dataclass
class Crystallization:
    id: str
    student_id: str
    topic: str
    question: str
    correct_answer: str
    explanation: str
    times_correct: int
    position: GeometricPosition
    tilt: TiltVector
    next_candidates: List[str]
    bridge: str
    depth_level: int = 0
    saved_at: float = field(default_factory=time.time)
    reference_count: int = 0
    edit_history: List[Dict] = field(default_factory=list)
    content_hash: str = ""

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        content = f"{self.question}|{self.correct_answer}|{self.explanation}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @property
    def needs_reinforcement(self) -> bool:
        return self.reference_count > 3

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "student_id": self.student_id, "topic": self.topic,
            "question": self.question, "correct_answer": self.correct_answer,
            "explanation": self.explanation, "times_correct": self.times_correct,
            "position": self.position.to_dict(), "tilt": self.tilt.to_dict(),
            "next_candidates": self.next_candidates, "bridge": self.bridge,
            "depth_level": self.depth_level, "saved_at": self.saved_at,
            "reference_count": self.reference_count, "edit_history": self.edit_history,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Crystallization":
        return cls(
            id=d["id"], student_id=d["student_id"], topic=d["topic"],
            question=d["question"], correct_answer=d["correct_answer"],
            explanation=d["explanation"], times_correct=d["times_correct"],
            position=GeometricPosition.from_dict(d.get("position", GeometricPosition.default().to_dict())),
            tilt=TiltVector.from_dict(d.get("tilt", {"alpha_delta": 0.1, "cave_delta": 0.1, "L_net_delta": 0.1})),
            next_candidates=d.get("next_candidates", []), bridge=d.get("bridge", ""),
            depth_level=d.get("depth_level", 0), saved_at=d.get("saved_at", time.time()),
            reference_count=d.get("reference_count", 0), edit_history=d.get("edit_history", []),
            content_hash=d.get("content_hash", ""),
        )

@dataclass
class StreakTracker:
    CRYSTALLIZE_AFTER: int = 3
    _streaks: Dict[str, int] = field(default_factory=dict)

    def record_correct(self, topic: str) -> bool:
        self._streaks[topic] = self._streaks.get(topic, 0) + 1
        return self._streaks[topic] >= self.CRYSTALLIZE_AFTER

    def record_incorrect(self, topic: str):
        self._streaks[topic] = 0

    def current_streak(self, topic: str) -> int:
        return self._streaks.get(topic, 0)

    def to_dict(self) -> Dict:
        return dict(self._streaks)

    def load_dict(self, d: Dict):
        self._streaks = dict(d)

# ════════════════════════════════════════════════════════════════════════
# §2 RAW SESSION STORE (ADMIN APPEND-ONLY LOG)
# ════════════════════════════════════════════════════════════════════════

@dataclass
class RawAnswerEvent:
    id: str
    student_id: str
    topic: str
    domain: str
    question: str
    student_answer: str
    correct_answer: str
    is_correct: bool
    streak_before: int     
    source: str = "llm"
    timestamp: float = field(default_factory=time.time)
    session_date: str = ""

    def __post_init__(self):
        if not self.session_date:
            self.session_date = time.strftime("%Y-%m-%d", time.localtime(self.timestamp))

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "student_id": self.student_id, "topic": self.topic, "domain": self.domain,
            "question": self.question, "student_answer": self.student_answer, "correct_answer": self.correct_answer,
            "is_correct": self.is_correct, "streak_before": self.streak_before, "source": self.source,
            "timestamp": self.timestamp, "session_date": self.session_date,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "RawAnswerEvent":
        return cls(**d)

    def to_csv_row(self) -> str:
        def esc(v: str) -> str:
            return f'"{str(v).replace(chr(34), chr(39))}"'
        return ",".join([
            esc(self.session_date), esc(self.student_id), esc(self.topic),
            esc(self.domain), esc(self.question), esc(self.student_answer),
            esc(self.correct_answer), esc("yes" if self.is_correct else "no"),
            esc(str(self.streak_before)), esc(self.source), esc(time.strftime("%H:%M:%S", time.localtime(self.timestamp))),
        ])

class RawSessionStore:
    SESSIONS_ROOT = Path("/data/sessions")

    def __init__(self, sessions_root: Optional[Path] = None, root: Optional[Path] = None):
        if sessions_root: self.SESSIONS_ROOT = sessions_root
        if root: self.SESSIONS_ROOT = root
        self.SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event: RawAnswerEvent):
        path = self.SESSIONS_ROOT / f"{event.student_id}.jsonl"
        try:
            with self._lock:
                with open(path, "a") as f:
                    f.write(json.dumps(event.to_dict()) + "\n")
        except Exception:
            pass 

    def load_student(self, student_id: str) -> List[RawAnswerEvent]:
        path = self.SESSIONS_ROOT / f"{student_id}.jsonl"
        if not path.exists(): return []
        events = []
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if line:
                    events.append(RawAnswerEvent.from_dict(json.loads(line)))
        except Exception:
            pass
        return sorted(events, key=lambda e: e.timestamp)

    def list_students(self) -> List[str]:
        return [p.stem for p in self.SESSIONS_ROOT.glob("*.jsonl")]

    def student_summary(self, student_id: str) -> Dict:
        events = self.load_student(student_id)
        if not events:
            return {"student_id": student_id, "total_attempts": 0, "correct": 0, "accuracy": 0.0, "topics_seen": []}
        correct = [e for e in events if e.is_correct]
        return {
            "student_id": student_id,
            "total_attempts": len(events),
            "correct": len(correct),
            "accuracy": round((len(correct) / len(events)) * 100, 1),
            "topics_seen": list({e.topic for e in events}),
            "first_seen": time.strftime("%Y-%m-%d %H:%M", time.localtime(events[0].timestamp)),
            "last_seen": time.strftime("%Y-%m-%d %H:%M", time.localtime(events[-1].timestamp)),
        }

    def export_csv(self, student_ids: Optional[List[str]] = None) -> str:
        header = ",".join(['"Date"', '"Student"', '"Topic"', '"Domain"', '"Question"', '"Student Answer"', '"Correct Answer"', '"Correct"', '"Streak Before"', '"Source"', '"Time"'])
        rows = [header]
        target_ids = student_ids if student_ids else self.list_students()
        for sid in sorted(target_ids):
            for event in self.load_student(sid):
                rows.append(event.to_csv_row())
        return "\n".join(rows)


# ════════════════════════════════════════════════════════════════════════
# §3 DYNAMIC LLM QUESTION GENERATOR & CACHE
# ════════════════════════════════════════════════════════════════════════

@dataclass
class GeneratedQuestion:
    topic: str
    domain: str
    question: str
    correct_answer: str
    explanation: str
    bridge: str
    difficulty: int = 1
    source: str = "llm" 
    generated_at: float = field(default_factory=time.time)

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "zh": "Mandarin Chinese",
    "ar": "Arabic",
    "hi": "Hindi",
    "pt": "Portuguese",
    "ru": "Russian",
    "sw": "Swahili",
    "tl": "Filipino (Tagalog)",
    "vi": "Vietnamese",
    "ko": "Korean",
    "so": "Somali",
    "am": "Amharic",
}

PROMPTS = {
    "arithmetic": (
        "Generate exactly {n} math questions for topic: {topic}. "
        "Principle: {principle}. Difficulty: {d}/3. "
        "Write ALL questions, answers, explanations, and bridges "
        "in {language}. "
        "Respond ONLY with a JSON array. Keys per item: "
        "question, correct_answer, explanation, bridge, difficulty."
    ),
    "reading": (
        "Generate exactly {n} reading/phonics questions for topic: {topic}. "
        "Principle: {principle}. Difficulty: {d}/3. "
        "Write ALL questions, answers, explanations, and bridges "
        "in {language}. "
        "Respond ONLY with a JSON array. Keys per item: "
        "question, correct_answer, explanation, bridge, difficulty."
    ),
    "default": (
        "Generate exactly {n} educational questions for topic: {topic}. "
        "Principle: {principle}. Difficulty: {d}/3. "
        "Write ALL questions, answers, explanations, and bridges "
        "in {language}. "
        "Respond ONLY with a JSON array. Keys per item: "
        "question, correct_answer, explanation, bridge, difficulty."
    ),
}

class LLMClient:
    DEFAULT_BASE_URL = "http://localhost:1234/v1"
    DEFAULT_MODEL    = "local-model"
    BATCH_SIZE       = 8
    MAX_RETRIES      = 2

    def __init__(self):
        self.base_url = os.environ.get("LLM_BASE_URL", self.DEFAULT_BASE_URL)
        self.api_key  = os.environ.get("LLM_API_KEY",  "lm-studio")
        self.model    = os.environ.get("LLM_MODEL",    self.DEFAULT_MODEL)
        self._client  = OpenAI(base_url=self.base_url, api_key=self.api_key) if OPENAI_AVAILABLE else None
        self._available = OPENAI_AVAILABLE

    def generate_questions(self, topic: str, domain: str, principle: str, difficulty: int = 1, language: str = "English") -> Optional[List[Dict]]:
        if not self._available: return None
        prompt = PROMPTS.get(domain, PROMPTS["default"]).format(
            topic=topic.replace("_", " "), principle=principle,
            d=difficulty, n=self.BATCH_SIZE, language=language
        )
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": "Always respond with valid JSON array only."}, {"role": "user", "content": prompt}],
                    temperature=0.7, max_tokens=2048,
                )
                raw = response.choices[0].message.content.strip()
                parsed = self._parse_response(raw)
                if parsed: return parsed
            except Exception:
                time.sleep(1)
        return None

    def _parse_response(self, raw: str) -> Optional[List[Dict]]:
        start, end = raw.find("["), raw.rfind("]")
        if start == -1 or end == -1: return None
        try:
            data = json.loads(raw[start:end + 1])
            valid = [i for i in data if isinstance(i, dict) and {"question", "correct_answer", "explanation", "bridge"}.issubset(i.keys())]
            return valid if valid else None
        except json.JSONDecodeError:
            return None

class QuestionCache:
    REFILL_THRESHOLD = 2
    MAX_QUEUE_SIZE   = 50
    BATCH            = 8

    def __init__(self, llm_client: LLMClient, domain_model: "DomainKnowledgeModel",
                 dispatcher: Optional[OllamaDispatcher] = None):
        self._client = llm_client
        self._domain = domain_model
        self._dispatcher = dispatcher
        self._queues = {}
        self._filling = {}
        self._lock = threading.Lock()
        self._used = {}

    def _get_queue(self, cache_key: str) -> queue.Queue:
        with self._lock:
            if cache_key not in self._queues:
                self._queues[cache_key]  = queue.Queue(maxsize=self.MAX_QUEUE_SIZE)
                self._filling[cache_key] = False
                self._used[cache_key]    = []
        return self._queues[cache_key]

    def get_question(self, topic: str, domain: str,
                     lang: str = "en") -> GeneratedQuestion:
        q = self._get_queue(f"{topic}:{lang}")        # key includes language
        if q.qsize() <= self.REFILL_THRESHOLD:
            self._trigger(topic, domain, Priority.NORMAL, lang)
        try:
            gq = q.get_nowait()
            with self._lock:
                used_key = f"{topic}:{lang}"
                self._used.setdefault(used_key, []).append(gq)
            return gq
        except queue.Empty:
            return self._fallback(topic, domain, lang)

    def _trigger(self, topic: str, domain: str,
                 priority: int = Priority.NORMAL,
                 lang: str = "en"):
        cache_key = f"{topic}:{lang}"
        with self._lock:
            if self._filling.get(cache_key):
                return
            self._filling[cache_key] = True

        principle    = (self._domain._domains.get(domain, {})
                        .get("topics", {}).get(topic, {})
                        .get("principle", ""))
        language_name = LANGUAGE_NAMES.get(lang, "English")

        prompt = PROMPTS.get(domain, PROMPTS["default"]).format(
            n=self.BATCH, topic=topic.replace("_", " "),
            principle=principle, d=1,
            language=language_name,
        )

        def on_result(raw: Optional[str]):
            try:
                if not raw:
                    raise ValueError("empty")
                items = _parse_questions(raw)
                if items:
                    q = self._get_queue(cache_key)
                    for item in items:
                        if q.full():
                            break
                        try:
                            q.put_nowait(GeneratedQuestion(
                                topic=topic, domain=domain,
                                question=item["question"],
                                correct_answer=str(item["correct_answer"]).strip(),
                                explanation=item["explanation"],
                                bridge=item["bridge"],
                                source="ollama",
                            ))
                        except queue.Full:
                            break
            except Exception as e:
                print(f"[CACHE] Fill error ({topic}/{lang}): {e}")
            finally:
                with self._lock:
                    self._filling[cache_key] = False

        if self._dispatcher:
            self._dispatcher.submit(
                student_id=f"__cache_{topic}_{lang}",
                prompt=prompt, callback=on_result,
                priority=priority, timeout=20.0,
            )
        else:
            # Fallback: use LLMClient in a background thread
            def _thread_fill():
                language_name_ = LANGUAGE_NAMES.get(lang, "English")
                raw_questions = self._client.generate_questions(
                    topic=topic, domain=domain, principle=principle,
                    difficulty=1, language=language_name_,
                )
                raw_str = json.dumps(raw_questions) if raw_questions else None
                on_result(raw_str)
            threading.Thread(target=_thread_fill, daemon=True).start()

    def _fallback(self, topic: str, domain: str, lang: str = "en") -> GeneratedQuestion:
        used_count = len(self._used.get(f"{topic}:{lang}", []))
        q_text, correct, explanation = ("What is 2 + 2?", "4", "2 + 2 = 4.")
        if topic == "addition_basic" and used_count % 2 == 1:
            q_text, correct, explanation = ("What is 3 + 3?", "6", "3 + 3 = 6.")
        return GeneratedQuestion(topic=topic, domain=domain, question=q_text, correct_answer=correct, explanation=explanation, bridge=f"If {q_text} = {correct}, what comes next?", source="fallback")

    def warm_cache(self, topics: List[Tuple[str, str]]):
        for topic, domain in topics:
            self._trigger(topic, domain, Priority.NORMAL, "en")

class ContextualRequester:
    def __init__(self, cache: QuestionCache, domain_model: "DomainKnowledgeModel",
                 branches=None, dispatcher=None):
        self._cache = cache
        self._domain = domain_model
        self._branches = branches
        self._dispatcher = dispatcher
        self._next = {}
        self._lock = threading.Lock()

    def get_next(self, student_id: str, topic: str,
                 domain: str, lang: str = "en") -> GeneratedQuestion:
        with self._lock:
            pre = self._next.pop(student_id, None)
        self._schedule(student_id, topic, domain, lang)
        return pre or self._cache.get_question(topic, domain, lang)

    def _schedule(self, student_id: str, topic: str,
                  domain: str, lang: str = "en"):
        if not self._branches or not self._dispatcher:
            return
        agent = self._branches.get_agent(student_id) if hasattr(self._branches, 'get_agent') else self._branches.get(student_id)
        if not agent:
            return
        language_name = LANGUAGE_NAMES.get(lang, "English")
        principle = (self._domain._domains.get(domain, {})
                     .get("topics", {}).get(topic, {})
                     .get("principle", ""))
        prompt = (
            f"You are tutoring a student. Learning history:\n\n"
            f"{agent.get_context()}\n\n"
            f"Generate ONE question for topic '{topic.replace('_', ' ')}' "
            f"(principle: {principle}). "
            f"Write the question, answer, explanation, and bridge "
            f"entirely in {language_name}. "
            f"Match difficulty to their recent trajectory. "
            f"Respond ONLY with JSON: "
            f'{{\"question\": ..., \"correct_answer\": ..., '
            f'\"explanation\": ..., \"bridge\": ...}}'
        )

        def on_result(raw: Optional[str]):
            try:
                if not raw:
                    return
                data = json.loads(raw.strip())
                if isinstance(data, list):
                    data = data[0]
                gq = GeneratedQuestion(
                    topic=topic, domain=domain,
                    question=data["question"],
                    correct_answer=str(data["correct_answer"]).strip(),
                    explanation=data["explanation"],
                    bridge=data.get("bridge", ""),
                    source="contextual",
                )
                with self._lock:
                    self._next[student_id] = gq
            except Exception as e:
                print(f"[CTX] Schedule error ({student_id}/{topic}/{lang}): {e}")

        self._dispatcher.submit(
            student_id=student_id,
            prompt=prompt, callback=on_result,
            priority=Priority.HIGH, timeout=15.0,
        )

# ════════════════════════════════════════════════════════════════════════
# §4 DOMAIN KNOWLEDGE MODEL & SESSION MANAGEMENT
# ════════════════════════════════════════════════════════════════════════

class DomainKnowledgeModel:
    def __init__(self):
        self._domains: Dict[str, Dict] = {}
        self._domains["arithmetic"] = {
            "progression": ["counting", "addition_basic", "doubling", "multiplication_intro"],
            "topics": {
                "addition_basic": {
                    "principle": "adding a number to itself doubles it",
                    "tilt_alpha": {"candidates": ["n + n = 2n"], "bridge": "You know {fact}. What pattern do you see?"},
                },
                "doubling": {
                    "principle": "doubling means adding a number to itself",
                    "tilt_alpha": {"candidates": ["x2 notation"], "bridge": "You know {fact}. What is a shorter way to write it?"},
                }
            }
        }
        self._domains["reading"] = {
            "progression": ["alphabet", "phonics_basic", "cvc_words", "sight_words"],
            "topics": {
                "phonics_basic": {
                    "principle": "letters represent specific sounds",
                    "tilt_alpha": {"candidates": ["vowel rules"], "bridge": "You know {fact}. Do all letters make the same sound?"},
                }
            }
        }

    def get_tilt_data(self, domain: str, topic: str, tilt: TiltVector) -> Dict:
        topic_data = self._domains.get(domain, {}).get("topics", {}).get(topic, {})
        if not topic_data: return {"candidates": [], "bridge": "Keep exploring!"}
        tilt_key = f"tilt_{tilt.dominant_dimension}"
        return topic_data.get(tilt_key, topic_data.get("tilt_alpha", {"candidates": [], "bridge": ""}))
      
    def get_depth(self, topic: str, domain: str) -> int:
        try: return self._domains.get(domain, {}).get("progression", []).index(topic)
        except ValueError: return 0

class SessionManager:
    STATE_ROOT = Path("/data/state")

    def __init__(self, state_root=None):
        if state_root:
            self.STATE_ROOT = state_root
        self.STATE_ROOT.mkdir(parents=True, exist_ok=True)
        self._students: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def get_or_create(self, student_id: str) -> Dict:
        with self._lock:
            if student_id not in self._students:
                self._students[student_id] = self._load(student_id)
            return self._students[student_id]

    def save_crystal(self, student_id: str, crystal):
        with self._lock:
            data = self.get_or_create(student_id)
            data["crystallizations"][crystal.id] = crystal
            self._persist(student_id)
            self._mirror_checkpoint(student_id)

    def get_crystals(self, student_id: str):
        with self._lock:
            data = self.get_or_create(student_id)
            return sorted(data["crystallizations"].values(),
                          key=lambda c: c.saved_at, reverse=True)

    def persist_position(self, student_id: str, position):
        data = self.get_or_create(student_id)
        data["position"] = position
        self._persist(student_id)

    def persist_current_question(self, student_id: str, gq):
        data = self.get_or_create(student_id)
        data["current_question_dict"] = {
            "topic": gq.topic, "domain": gq.domain,
            "question": gq.question, "correct_answer": gq.correct_answer,
            "explanation": gq.explanation, "bridge": gq.bridge,
            "difficulty": gq.difficulty, "source": gq.source,
        }
        self._persist(student_id)

    def all_student_ids(self):
        on_disk = [p.stem for p in self.STATE_ROOT.glob("*.json")]
        with self._lock:
            return list(set(on_disk + list(self._students.keys())))

    def _persist(self, student_id: str):
        data = self._students.get(student_id)
        if not data:
            return
        path = self.STATE_ROOT / f"{student_id}.json"
        try:
            path.write_text(json.dumps({
                "student_id":           student_id,
                "current_domain":       data["current_domain"],
                "current_topic":        data["current_topic"],
                "streaks":              data["streak_tracker"].to_dict(),
                "position":             data["position"].to_dict(),
                "crystallizations":     [c.to_dict() for c in data["crystallizations"].values()],
                "current_question_dict": data.get("current_question_dict"),
                "saved_at":             time.time(),
                "language":             data.get("language", "en"),
            }, indent=2))
        except Exception as e:
            print(f"[STATE] Persist failed {student_id}: {e}")

    def _load(self, student_id: str) -> Dict:
        default = {
            "streak_tracker":       StreakTracker(),
            "crystallizations":     {},
            "current_domain":       "arithmetic",
            "current_topic":        "addition_basic",
            "position":             GeometricPosition.default(),
            "current_question":     None,
            "current_question_dict": None,
            "language":             "en",
        }
        path = self.STATE_ROOT / f"{student_id}.json"
        if not path.exists():
            return default
        try:
            raw     = json.loads(path.read_text())
            tracker = StreakTracker()
            tracker.load_dict(raw.get("streaks", {}))
            crystals = {}
            for d in raw.get("crystallizations", []):
                try:
                    c = Crystallization.from_dict(d)
                    crystals[c.id] = c
                except Exception:
                    pass
            current_question = None
            cqd = raw.get("current_question_dict")
            if cqd:
                try:
                    current_question = GeneratedQuestion(**cqd)
                except Exception:
                    pass
            return {
                "streak_tracker":       tracker,
                "crystallizations":     crystals,
                "current_domain":       raw.get("current_domain", "arithmetic"),
                "current_topic":        raw.get("current_topic", "addition_basic"),
                "position":             GeometricPosition.from_dict(
                    raw.get("position", GeometricPosition.default().to_dict())),
                "current_question":     current_question,
                "current_question_dict": cqd,
                "language":             raw.get("language", "en"),
            }
        except Exception as e:
            print(f"[STATE] Load failed {student_id}: {e}")
            return default

    def _mirror_checkpoint(self, student_id: str):
        path = Path("/data/checkpoints") / f"{student_id}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = self._students.get(student_id, {})
            crystals = list(data.get("crystallizations", {}).values())
            path.write_text(json.dumps([c.to_dict() for c in crystals], indent=2))
        except Exception as e:
            print(f"[STATE] Checkpoint mirror failed {student_id}: {e}")
class MicroRAGManager:
    """
    Ruthless context pruning for 32M parameter models.
    Bypasses vector databases. Uses strict topological filtering
    and lightweight lexical overlap to guarantee < 50 token payloads.
    """
    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager

    def _tokenize(self, text: str) -> set:
        """Basic lexical tokenizer for lightweight overlap scoring."""
        words = re.findall(r'\b\w+\b', text.lower())
        stop_words = {"what", "is", "the", "a", "an", "of", "to", "how", "many"}
        return set(words) - stop_words

    def retrieve_hyper_local_context(
        self, 
        student_id: str, 
        current_topic: str, 
        current_question: str
    ) -> Optional[Dict]:
        checkpoints = self.session_manager.get_crystals(student_id)
      
        # 1. Topological Filter
        topic_checkpoints = [c for c in checkpoints if c.topic == current_topic]
        if not topic_checkpoints:
            return None

        # 2. Lexical Scoring (Jaccard-lite) + Recency Weight
        target_tokens = self._tokenize(current_question)
        best_checkpoint = None
        highest_score = -1.0

        for cp in topic_checkpoints:
            cp_tokens = self._tokenize(cp.question)
            overlap = len(target_tokens.intersection(cp_tokens))
          
            # Recency bias: newer crystallizations carry higher weight
            age_penalty = (time.time() - cp.saved_at) / 86400  
            score = (overlap * 2.0) + cp.times_correct - (age_penalty * 0.1)
          
            if score > highest_score:
                highest_score = score
                best_checkpoint = cp

        if not best_checkpoint:
            return None

        # 3. Ruthless Pruning
        return {
            "fact": f"{best_checkpoint.question} = {best_checkpoint.correct_answer}",
            "bridge": best_checkpoint.bridge,
            "raw_checkpoint": best_checkpoint
        }

# ════════════════════════════════════════════════════════════════════════
# §5 NFC PHYSICAL STATION REGISTRY
# ════════════════════════════════════════════════════════════════════════

@dataclass
class Station:
    id: str
    topic: str
    domain: str
    label: str        
    location: str        
    color: str        
    active: bool = True
    scan_count: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {"id": self.id, "topic": self.topic, "domain": self.domain, "label": self.label, "location": self.location, "color": self.color, "active": self.active, "scan_count": self.scan_count, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, d: Dict) -> "Station":
        return cls(**d)

class StationRegistry:
    STORAGE_PATH = Path("/data/stations/stations.json")

    def __init__(self, storage_path: Optional[Path] = None, path: Optional[Path] = None):
        if storage_path: self.STORAGE_PATH = storage_path
        if path: self.STORAGE_PATH = path
        self.STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._stations: Dict[str, Station] = {}
        self._lock = threading.Lock()
        self._load()
        if not self._stations: self._seed_defaults()

    def _seed_defaults(self):
        defaults = [
            ("addition_basic", "arithmetic", "Addition Station", "Back wall", "#3b82f6"),
            ("phonics_basic", "reading", "Phonics Station", "Library area", "#ef4444"),
        ]
        for t, d, l, loc, c in defaults:
            s = Station(id=f"station-{uuid.uuid4().hex[:6]}", topic=t, domain=d, label=l, location=loc, color=c)
            self._stations[s.id] = s
        self._save()

    def get(self, station_id: str) -> Optional[Station]:
        return self._stations.get(station_id)

    def all_stations(self) -> List[Station]:
        return sorted([s for s in self._stations.values() if s.active], key=lambda s: s.label)

    def all_active(self) -> List[Station]:
        return self.all_stations()

    def increment_scan(self, station_id: str):
        with self._lock:
            if station_id in self._stations: self._stations[station_id].scan_count += 1
        self._save()

    def _save(self):
        self.STORAGE_PATH.write_text(json.dumps([s.to_dict() for s in self._stations.values()], indent=2))

    def _load(self):
        if self.STORAGE_PATH.exists():
            for d in json.loads(self.STORAGE_PATH.read_text()):
                s = Station.from_dict(d)
                self._stations[s.id] = s

# ════════════════════════════════════════════════════════════════════════
# §6 TEACHER & ADMIN AUTHENTICATION
# ════════════════════════════════════════════════════════════════════════

class TeacherAuth:
    AUTH_PATH = Path("/data/auth/teachers.json")
    ITERATIONS = 260_000

    def __init__(self):
        self.AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._accounts, self._sessions = {}, {}
        self._lock = threading.Lock()
        self._load()

    def create_account(self, username, password):
        if username in self._accounts: return False
        salt = secrets.token_hex(32)
        self._accounts[username] = {"username": username, "pw_hash": self._hash(password, salt), "salt": salt}
        self._save()
        return True

    def login(self, username, password):
        acc = self._accounts.get(username)
        if acc and hmac.compare_digest(self._hash(password, acc["salt"]), acc["pw_hash"]):
            token = secrets.token_hex(32)
            with self._lock: self._sessions[token] = {"username": username, "expires": time.time() + 28800}
            return token
        return None

    def validate_token(self, token):
        s = self._sessions.get(token)
        return s["username"] if s and time.time() < s["expires"] else None

    def _hash(self, password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), self.ITERATIONS).hex()

    def _save(self): self.AUTH_PATH.write_text(json.dumps(self._accounts))

    def _load(self):
        if self.AUTH_PATH.exists(): self._accounts = json.loads(self.AUTH_PATH.read_text())


class AdminAuth:
    AUTH_PATH = Path("/data/auth/admin.json")

    def __init__(self):
        self.AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._account, self._session = None, None
        self._load()

    def setup(self, username, password):
        if self._account: return False
        salt = secrets.token_hex(32)
        self._account = {"username": username, "pw_hash": hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000).hex(), "salt": salt}
        self._save()
        return True

    def login(self, username, password):
        if self._account and username == self._account["username"]:
            if hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", password.encode(), self._account["salt"].encode(), 260000).hex(), self._account["pw_hash"]):
                token = secrets.token_hex(32)
                self._session = {"token": token, "expires": time.time() + 28800}
                return token
        return None

    def validate_token(self, token):
        return bool(self._session and self._session["token"] == token and time.time() < self._session["expires"])

    def _save(self): self.AUTH_PATH.write_text(json.dumps(self._account or {}))

    def _load(self):
        if self.AUTH_PATH.exists(): self._account = json.loads(self.AUTH_PATH.read_text())

# ════════════════════════════════════════════════════════════════════════
# §7 HTML TEMPLATES
# ════════════════════════════════════════════════════════════════════════

STUDENT_TEMPLATE = """
<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>body{font-family:system-ui; background:#f4f4f5; margin:0; padding:2rem;} .card{background:white; padding:2rem; border-radius:8px; box-shadow:0 4px 6px -1px rgb(0 0 0 / 0.1); margin-bottom:2rem;} .btn{background:#3b82f6; color:white; padding:0.5rem 1rem; border:none; border-radius:4px; cursor:pointer;} input{width:100%; padding:0.75rem; border:1px solid #d4d4d8; margin-bottom:1rem;}</style></head>
<body>

<!-- Language selector — top of page -->
<div style="text-align:right;padding:.5rem 2rem;background:#e0e7ff;">
  <form action="/set_language" method="POST" style="display:inline;">
    <select name="lang" onchange="this.form.submit()"
            style="padding:.3rem;border-radius:4px;border:1px solid #c7d2fe;">
      <option value="en"  {% if lang == 'en'  %}selected{% endif %}>English</option>
      <option value="es"  {% if lang == 'es'  %}selected{% endif %}>Español</option>
      <option value="fr"  {% if lang == 'fr'  %}selected{% endif %}>Français</option>
      <option value="zh"  {% if lang == 'zh'  %}selected{% endif %}>中文</option>
      <option value="ar"  {% if lang == 'ar'  %}selected{% endif %}>العربية</option>
      <option value="hi"  {% if lang == 'hi'  %}selected{% endif %}>हिन्दी</option>
      <option value="pt"  {% if lang == 'pt'  %}selected{% endif %}>Português</option>
      <option value="ru"  {% if lang == 'ru'  %}selected{% endif %}>Русский</option>
      <option value="sw"  {% if lang == 'sw'  %}selected{% endif %}>Kiswahili</option>
      <option value="tl"  {% if lang == 'tl'  %}selected{% endif %}>Filipino</option>
      <option value="vi"  {% if lang == 'vi'  %}selected{% endif %}>Tiếng Việt</option>
      <option value="ko"  {% if lang == 'ko'  %}selected{% endif %}>한국어</option>
      <option value="so"  {% if lang == 'so'  %}selected{% endif %}>Soomaali</option>
      <option value="am"  {% if lang == 'am'  %}selected{% endif %}>አማርኛ</option>
    </select>
  </form>
</div>

    <h2>Challenge: {{ current_topic.replace('_', ' ') }}</h2>
    <div class="card">
        <form action="/submit" method="POST">
            <label>{{ current_question }}</label>
            <input type="text" name="answer" autofocus autocomplete="off"
                   dir="auto"
                   style="width:100%;padding:.75rem;border:1px solid #d4d4d8;
                          margin-bottom:1rem;box-sizing:border-box;
                          font-size:1.1rem;">
            <button type="submit" class="btn">Submit Answer</button>
        </form>
        {% if message %} <p style="color: #065f46; background: #ecfdf5; padding: 1rem;">{{ message }}</p> {% endif %}
    </div>
  
    <div class="card">
        <h3>Crystallized Knowledge</h3>
        {% for c in crystals %}
            <div style="background:#fafafa; padding:1rem; margin-bottom:1rem; border:1px solid #ddd;">
                <strong>Q:</strong> {{ c.question }} <br>
                <strong>A:</strong> {{ c.correct_answer }} <br>
                <em>{{ c.bridge }}</em>
                <form action="/reference/{{ c.id }}" method="POST" style="margin-top:0.5rem;"><button class="btn" style="background:#10b981; font-size:0.8rem;">Reference Concept</button></form>
            </div>
        {% endfor %}
    </div>
</body></html>
"""

ADMIN_DASHBOARD_TEMPLATE = """
<!DOCTYPE html><html><head><style>body{font-family:system-ui; background:#18181b; color:#e4e4e7; padding:2rem;} .card{background:#27272a; padding:2rem; border-radius:8px; margin-bottom:2rem;} table{width:100%; border-collapse:collapse;} th,td{padding:0.5rem; border-bottom:1px solid #3f3f46; text-align:left;} a{color:#60a5fa;}</style></head>
<body>
    <h1>FOTNSSJ Admin</h1>
    <div class="card">
        <h2>School Overview</h2>
        <p>Students: {{ total_students }} | Accuracy: {{ school_accuracy }}% | Total Checkpoints: {{ total_checkpoints }}</p>
        <a href="/admin/export/all" style="background:#3b82f6; padding:0.5rem; color:white; text-decoration:none; border-radius:4px;">Export Raw CSV Data</a>
    </div>
    <div class="card">
        <h2>Student Summaries</h2>
        <table><tr><th>Student</th><th>Attempts</th><th>Accuracy</th><th>Checkpoints</th></tr>
        {% for s in summaries %}
            <tr><td>{{ s.student_id }}</td><td>{{ s.total_attempts }}</td><td>{{ s.accuracy }}%</td><td>{{ s.checkpoint_count }}</td></tr>
        {% endfor %}
        </table>
    </div>
</body></html>
"""

STATION_TEMPLATE = """
<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>body{font-family:system-ui; padding:2rem; text-align:center;} .card{background:white; padding:2rem; border-radius:8px; box-shadow:0 4px 6px -1px rgb(0 0 0 / 0.1); margin: 0 auto; max-width: 400px;} .btn{background:{{ station.color }}; color:white; padding:0.75rem 2rem; border:none; border-radius:4px; font-size:1.2rem; margin-top:1rem; width:100%;}</style></head>
<body>
    <h2 style="color:{{ station.color }}">{{ station.label }}</h2>
    <div class="card">
        <h3>{{ question.question }}</h3>
        <form action="/station/{{ station.id }}/answer" method="POST">
            <input type="text" name="answer" style="width:100%; padding:1rem; font-size:1.2rem; box-sizing:border-box;" autofocus autocomplete="off">
            <button type="submit" class="btn">Submit</button>
        </form>
        {% if message %}<p style="margin-top:1rem; font-weight:bold;">{{ message }}</p>{% endif %}
      
        <form action="/station/{{ station.id }}/reference" method="POST" style="margin-top: 2rem;">
            <button class="btn" style="background:#6b7280; font-size:0.9rem;">Need a hint? Reference Past Knowledge</button>
        </form>
      
        {% if reference %}
            <div style="background:#f3f4f6; padding:1rem; margin-top:1rem; text-align:left;">
                <strong>You already know:</strong> {{ reference.question }} = {{ reference.correct_answer }}<br>
                <em>{{ reference.bridge }}</em>
            </div>
        {% endif %}
    </div>
</body></html>
"""

# ════════════════════════════════════════════════════════════════════════
# §8 FLASK APP INITIALIZATION
# ════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

def ts_time_filter(value: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(value))
app.jinja_env.filters["ts_time"] = ts_time_filter

knowledge_model   = DomainKnowledgeModel()
session_manager   = SessionManager()
raw_session_store = RawSessionStore()
llm_client        = LLMClient()
dispatcher        = OllamaDispatcher()
question_cache    = QuestionCache(llm_client, knowledge_model, dispatcher=dispatcher)
contextual_q      = ContextualRequester(question_cache, knowledge_model, dispatcher=dispatcher)
station_registry  = StationRegistry()
geometry_manifest = GeometryManifest()
teacher_auth      = TeacherAuth()
admin_auth        = AdminAuth()

# Warm up core AI questions in the background
question_cache.warm_cache([("addition_basic", "arithmetic"), ("phonics_basic", "reading")])

# Ensure default users exist
if not teacher_auth._accounts: teacher_auth.create_account("teacher", "changeme123!")
if not admin_auth._account: admin_auth.setup(os.environ.get("ADMIN_USER", "admin"), os.environ.get("ADMIN_PASS", "adminpass123!"))

# ════════════════════════════════════════════════════════════════════════
# §9 FLASK ROUTES
# ════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if "student_id" not in session: session["student_id"] = f"student_{secrets.token_hex(4)}"
    return redirect(url_for("student_dashboard", student_id=session["student_id"]))

@app.route("/student/<student_id>")
def student_dashboard(student_id: str):
    session["student_id"] = student_id
    data = session_manager.get_or_create(student_id)
    topic, domain = data["current_topic"], data["current_domain"]
    lang = data.get("language", "en")

    if not data.get("current_question"):
        data["current_question"] = question_cache.get_question(topic, domain, lang=lang)
      
    crystals = session_manager.get_crystals(student_id)
    rendered = render_template_string(
        STUDENT_TEMPLATE, current_topic=topic, current_question=data["current_question"].question,
        crystals=crystals, message=request.args.get("message", ""), lang=lang
    )
    return rendered

@app.route("/set_language", methods=["POST"])
def set_language():
    student_id = session.get("student_id")
    if not student_id:
        return redirect(url_for("index"))

    lang = request.form.get("lang", "en")
    allowed = {"en","es","fr","zh","ar","hi","pt","ru","sw","tl","vi","ko","so","am"}
    if lang not in allowed:
        lang = "en"

    data = session_manager.get_or_create(student_id)
    data["language"] = lang
    session_manager.persist_position(student_id, data["position"])
    data["current_question"] = None

    return redirect(url_for("student_dashboard", student_id=student_id))

@app.route("/submit", methods=["POST"])
def submit_answer():
    student_id = session.get("student_id")
    if not student_id: return redirect(url_for("index"))
  
    answer = request.form.get("answer", "").strip().lower()
    data = session_manager.get_or_create(student_id)
    topic, domain = data["current_topic"], data["current_domain"]
    lang = data.get("language", "en")

    gq = data.get("current_question") or question_cache.get_question(topic, domain, lang=lang)
    is_correct = _answers_match(answer, gq.correct_answer)
    tracker = data["streak_tracker"]
    streak_before = tracker.current_streak(topic)

    # 1. Write to Raw Session Store First
    raw_session_store.record(RawAnswerEvent(
        id=str(uuid.uuid4()), student_id=student_id, topic=topic, domain=domain,
        question=gq.question, student_answer=answer, correct_answer=gq.correct_answer,
        is_correct=is_correct, streak_before=streak_before, source=gq.source
    ))

    # 2. Crystallization Logic
    if is_correct:
        if tracker.record_correct(topic):
            tilt = TiltVector(0.5, 0.3, 0.2)
            bridge = gq.bridge or f"If {gq.question} = {gq.correct_answer}, what comes next?"
            crystal = Crystallization(
                id=str(uuid.uuid4()), student_id=student_id, topic=topic,
                question=gq.question, correct_answer=gq.correct_answer, explanation=gq.explanation,
                times_correct=tracker.current_streak(topic), position=data["position"], tilt=tilt,
                next_candidates=[], bridge=bridge, depth_level=knowledge_model.get_depth(topic, domain)
            )
            session_manager.save_crystal(student_id, crystal)
            tracker.record_incorrect(topic)
            msg = "Crystallized into your knowledge bank!"
        else:
            msg = f"Correct! Streak: {tracker.current_streak(topic)}/{tracker.CRYSTALLIZE_AFTER}"
    else:
        tracker.record_incorrect(topic)
        msg = f"Not quite — the answer is {gq.correct_answer}. Streak reset."

    data["current_question"] = contextual_q.get_next(student_id, topic, domain, lang=lang)
    return redirect(url_for("student_dashboard", student_id=student_id, message=msg))

@app.route("/reference/<crystal_id>", methods=["POST"])
def reference_crystal(crystal_id: str):
    student_id = session.get("student_id")
    if not student_id: return redirect(url_for("index"))
    data = session_manager.get_or_create(student_id)
    crystal = data["crystallizations"].get(crystal_id)
  
    if crystal:
        crystal.reference_count += 1
        msg = f"📚 You referenced '{crystal.topic}'. (Uses: {crystal.reference_count})"
    else:
        msg = "Reference not found."
    return redirect(url_for("student_dashboard", student_id=student_id, message=msg))

# --- NFC STATION ROUTES ---
_station_questions = {}
_station_qs = _station_questions  # alias for tests


def _get_station_q(key, fallback):
    """Retrieve question from station cache, handling (gq, timestamp) tuples."""
    val = _station_questions.get(key)
    if val is None:
        return fallback
    if isinstance(val, tuple):
        return val[0]
    return val

@app.route("/station/<station_id>")
def station_view(station_id: str):
    if "student_id" not in session: session["student_id"] = f"student_{secrets.token_hex(4)}"
    student_id = session["student_id"]
    station = station_registry.get(station_id)
    if not station or not station.active: return "Station not found.", 404
  
    station_registry.increment_scan(station_id)
    fallback = question_cache.get_question(station.topic, station.domain)
    gq = _get_station_q((student_id, station_id), fallback)
    if (student_id, station_id) not in _station_questions:
        _station_questions[(student_id, station_id)] = gq

    return render_template_string(STATION_TEMPLATE, station=station, question=gq, message=request.args.get("message", ""))

@app.route("/station/<station_id>/answer", methods=["POST"])
def station_answer(station_id: str):
    student_id = session.get("student_id")
    station = station_registry.get(station_id)
    if not student_id or not station: return redirect("/")
  
    answer = request.form.get("answer", "").strip().lower()
    data = session_manager.get_or_create(student_id)
    gq = _get_station_q((student_id, station_id), question_cache.get_question(station.topic, station.domain))
    is_correct = _answers_match(answer, gq.correct_answer)

    tracker = data["streak_tracker"]
    raw_session_store.record(RawAnswerEvent(
        id=str(uuid.uuid4()), student_id=student_id, topic=station.topic, domain=station.domain,
        question=gq.question, student_answer=answer, correct_answer=gq.correct_answer,
        is_correct=is_correct, streak_before=tracker.current_streak(station.topic), source=gq.source
    ))
  
    if is_correct:
        if tracker.record_correct(station.topic):
            crystal = Crystallization(id=str(uuid.uuid4()), student_id=student_id, topic=station.topic, question=gq.question, correct_answer=gq.correct_answer, explanation=gq.explanation, times_correct=tracker.current_streak(station.topic), position=data["position"], tilt=TiltVector(0.5,0.3,0.2), next_candidates=[], bridge=gq.bridge, depth_level=1)
            session_manager.save_crystal(student_id, crystal)
            tracker.record_incorrect(station.topic)
            msg = "Crystallized! Move to the next station."
            _station_questions.pop((student_id, station_id), None)
        else:
            msg = f"Correct! {tracker.current_streak(station.topic)}/{tracker.CRYSTALLIZE_AFTER}"
            _station_questions.pop((student_id, station_id), None)
    else:
        tracker.record_incorrect(station.topic)
        msg = "Not quite. Try again!"
      
    return redirect(url_for("station_view", station_id=station_id, message=msg))

@app.route("/station/<station_id>/reference", methods=["POST"])
def station_reference(station_id: str):
    student_id = session.get("student_id")
    station = station_registry.get(station_id)
    if not student_id or not station: return redirect("/")
  
    crystals = session_manager.get_crystals(student_id)
    same_topic = [c for c in crystals if c.topic == station.topic]
    reference = max(same_topic or crystals, key=lambda c: c.saved_at) if crystals else None
  
    gq = _get_station_q((student_id, station_id), question_cache.get_question(station.topic, station.domain))
    return render_template_string(STATION_TEMPLATE, station=station, question=gq, reference=reference)

# --- ADMIN ROUTES ---
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET": return """<form method="POST">Username: <input name="username"><br>Password: <input type="password" name="password"><button>Login</button></form>"""
    token = admin_auth.login(request.form.get("username"), request.form.get("password"))
    if token: session["admin_token"] = token
    return redirect(url_for("admin_dashboard"))

@app.route("/admin")
def admin_dashboard():
    if not admin_auth.validate_token(session.get("admin_token")): return redirect(url_for("admin_login"))
    summaries = []
    total_a, total_c = 0, 0
    all_sids = set(raw_session_store.list_students()) | set(session_manager.all_student_ids())
  
    for sid in all_sids:
        s = raw_session_store.student_summary(sid)
        s["checkpoint_count"] = len(session_manager.get_crystals(sid))
        summaries.append(s)
        total_a += s["total_attempts"]
        total_c += s["correct"]
      
    return render_template_string(
        ADMIN_DASHBOARD_TEMPLATE, total_students=len(all_sids), total_attempts=total_a,
        total_correct=total_c, school_accuracy=round(total_c/total_a*100, 1) if total_a else 0,
        total_checkpoints=sum(s["checkpoint_count"] for s in summaries), summaries=summaries
    )

@app.route("/admin/export/all")
def admin_export_all():
    if not admin_auth.validate_token(session.get("admin_token")): return redirect(url_for("admin_login"))
    return Response(raw_session_store.export_csv(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=fotnssj_export_{int(time.time())}.csv"})

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "dispatcher": dispatcher.metrics,
        "geometry": geometry_manifest.summary(),
    })

ADMIN_GEOMETRY_TEMPLATE = """
<!DOCTYPE html><html><head><style>body{font-family:system-ui; background:#18181b; color:#e4e4e7; padding:2rem;} .card{background:#27272a; padding:2rem; border-radius:8px; margin-bottom:2rem;} table{width:100%; border-collapse:collapse;} th,td{padding:0.5rem; border-bottom:1px solid #3f3f46; text-align:left;} a{color:#60a5fa;} .critical{color:#ef4444;} .error{color:#f59e0b;} .warning{color:#a3a3a3;}</style></head>
<body>
    <h1>Geometry Manifest</h1>
    <div class="card">
        <h2>Summary</h2>
        <p>Unresolved: {{ summary.unresolved }} | Critical: {{ summary.critical_unresolved }} | Errors: {{ summary.error_unresolved }} | Warnings: {{ summary.warning_unresolved }}</p>
        <p>Affected students: {{ summary.affected_students|length }}</p>
        <a href="/admin/geometry/export" style="background:#3b82f6; padding:0.5rem; color:white; text-decoration:none; border-radius:4px;">Export JSON</a>
    </div>
    <div class="card">
        <h2>Unresolved Reports</h2>
        <table><tr><th>ID</th><th>Student</th><th>Type</th><th>Severity</th><th>Detail</th><th>Action</th></tr>
        {% for r in reports %}
            <tr>
                <td>{{ r.report_id }}</td>
                <td>{{ r.student_id }}</td>
                <td>{{ r.type_label }}</td>
                <td class="{{ r.severity }}">{{ r.severity }}</td>
                <td>{{ r.detail }}</td>
                <td><form action="/admin/geometry/ack/{{ r.report_id }}" method="POST" style="display:inline;"><button style="background:#10b981;color:white;border:none;padding:0.3rem 0.6rem;border-radius:4px;cursor:pointer;">Ack</button></form></td>
            </tr>
        {% endfor %}
        </table>
    </div>
</body></html>
"""

@app.route("/admin/geometry")
def admin_geometry():
    if not admin_auth.validate_token(session.get("admin_token")): return redirect(url_for("admin_login"))
    return render_template_string(
        ADMIN_GEOMETRY_TEMPLATE,
        summary=geometry_manifest.summary(),
        reports=geometry_manifest.unresolved(),
    )

@app.route("/admin/geometry/export")
def admin_geometry_export():
    if not admin_auth.validate_token(session.get("admin_token")): return redirect(url_for("admin_login"))
    return jsonify(geometry_manifest.all_reports())

@app.route("/admin/geometry/ack/<report_id>", methods=["POST"])
def admin_geometry_ack(report_id: str):
    if not admin_auth.validate_token(session.get("admin_token")): return redirect(url_for("admin_login"))
    geometry_manifest.acknowledge(report_id, "admin")
    return redirect(url_for("admin_geometry"))


# ════════════════════════════════════════════════════════════════════════
# §10 SEEDER & ENTRY POINT
# ════════════════════════════════════════════════════════════════════════

def seed_demo_data():
    demo_student = "demo_student"
    student_data = session_manager.get_or_create(demo_student)
    student_data["streak_tracker"]._streaks["addition_basic"] = 2
  
    crystal = Crystallization(
        id=str(uuid.uuid4()), student_id=demo_student, topic="counting",
        question="What comes after 4?", correct_answer="5", explanation="Numbers go up by 1 sequentially.",
        times_correct=5, position=GeometricPosition.default(), tilt=TiltVector(0.8, 0.1, 0.1),
        next_candidates=["addition_basic"], bridge="You know how to count to 5. What happens if we combine groups?",
        reference_count=2, depth_level=1
    )
    session_manager.save_crystal(demo_student, crystal)
    print("="*60)
    print(f"[*] Demo seeded! Student URL: [http://127.0.0.1:5000/student/](http://127.0.0.1:5000/student/){demo_student}")
    print("    Admin URL:   [http://127.0.0.1:5000/admin/login](http://127.0.0.1:5000/admin/login)")
    print("    Station Map: [http://127.0.0.1:5000/station/station-001](http://127.0.0.1:5000/station/station-001)  <-- Demo NFC endpoint")
    print("="*60)

if __name__ == "__main__":
    seed_demo_data()
    app.run(debug=True, host="0.0.0.0", port=5000)