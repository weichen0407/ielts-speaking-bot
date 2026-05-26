"""IELTS Exam Manager - Manages IELTS speaking exam flow."""

from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from enum import Enum
import json
import uuid


class ExamPart(Enum):
    PART1 = "part1"
    PART2 = "part2"
    PART3 = "part3"


class ExamState(Enum):
    IDLE = "idle"
    PART1_QUESTIONS = "part1_questions"
    PART2_CUE_CARD = "part2_cue_card"
    PART2_SPEAKING = "part2_speaking"
    PART3_QUESTIONS = "part3_questions"
    COMPLETED = "completed"


@dataclass
class ExamQuestion:
    """A single exam question."""
    number: int
    question: str
    depth: int
    asked: bool = False
    answer: str = ""
    time_spent: int = 0


@dataclass
class ExamCueCard:
    """Part 2 Cue Card."""
    topic: str
    bullet_points: list[str]
    asked: bool = False
    answer: str = ""
    prep_time: int = 0
    speak_time: int = 0


@dataclass
class ExamPartData:
    """Data for a single exam part."""
    part: ExamPart
    questions: list[ExamQuestion] = field(default_factory=list)
    cue_card: ExamCueCard | None = None


@dataclass
class ExamRecord:
    """Complete exam record."""
    exam_id: str
    topic: str
    topic_file: str
    started_at: str
    ended_at: str = ""
    state: ExamState = ExamState.IDLE
    current_part: ExamPart = ExamPart.PART1
    current_question_index: int = 0
    parts: dict[str, ExamPartData] = field(default_factory=dict)
    final_score: dict = field(default_factory=dict)

    @classmethod
    def from_topic(cls, topic_name: str, topic_file: str) -> "ExamRecord":
        """Create a new exam record from a topic."""
        return cls(
            exam_id=str(uuid.uuid4()),
            topic=topic_name,
            topic_file=topic_file,
            started_at=datetime.utcnow().isoformat() + "Z",
        )

    def to_dict(self) -> dict:
        return {
            "exam_id": self.exam_id,
            "topic": self.topic,
            "topic_file": self.topic_file,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "state": self.state.value,
            "current_part": self.current_part.value,
            "current_question_index": self.current_question_index,
            "parts": {
                k: {
                    "part": v.part.value,
                    "questions": [
                        {
                            "number": q.number,
                            "question": q.question,
                            "depth": q.depth,
                            "asked": q.asked,
                            "answer": q.answer,
                            "time_spent": q.time_spent,
                        }
                        for q in v.questions
                    ],
                    "cue_card": {
                        "topic": v.cue_card.topic,
                        "bullet_points": v.cue_card.bullet_points,
                        "asked": v.cue_card.asked,
                        "answer": v.cue_card.answer,
                        "prep_time": v.cue_card.prep_time,
                        "speak_time": v.cue_card.speak_time,
                    } if v.cue_card else None,
                }
                for k, v in self.parts.items()
            },
            "final_score": self.final_score,
        }


class IeltsExamManager:
    """Manages IELTS speaking exam state and flow."""

    # Timing constants (seconds)
    PART1_PREP_TIME = 0  # No prep for Part 1
    PART1_ANSWER_TIME = 30
    PART2_PREP_TIME = 60
    PART2_SPEAK_TIME = 120
    PART3_PREP_TIME = 0
    PART3_ANSWER_TIME = 45

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self._exams_dir = self.workspace / "persona" / "ielts_exams"
        self._exams_dir.mkdir(parents=True, exist_ok=True)
        self._active_exam: ExamRecord | None = None

    def load_topic(self, topic_file: Path) -> ExamRecord:
        """Load a topic file and create a new exam record."""
        content = topic_file.read_text(encoding="utf-8")
        topic_name = topic_file.stem  # e.g., "01_animals" -> "01_animals"

        exam = ExamRecord.from_topic(topic_name, str(topic_file))

        # Parse Part 1 questions
        part1_questions = self._parse_part1(content)
        exam.parts["part1"] = ExamPartData(
            part=ExamPart.PART1,
            questions=part1_questions,
        )

        # Parse Part 2 Cue Card
        cue_card = self._parse_part2_cue_card(content)
        exam.parts["part2"] = ExamPartData(
            part=ExamPart.PART2,
            cue_card=cue_card,
        )

        # Parse Part 3 questions
        part3_questions = self._parse_part3(content)
        exam.parts["part3"] = ExamPartData(
            part=ExamPart.PART3,
            questions=part3_questions,
        )

        exam.state = ExamState.PART1_QUESTIONS
        exam.current_part = ExamPart.PART1
        exam.current_question_index = 0

        # Save to disk immediately
        self._save_exam(exam)
        self._active_exam = exam
        return exam

    def get_exam_by_id(self, exam_id: str) -> ExamRecord | None:
        """Load an exam record by ID from disk."""
        exam_file = self._exams_dir / f"{exam_id}.json"
        if not exam_file.exists():
            return None

        try:
            data = json.loads(exam_file.read_text(encoding="utf-8"))
            return self._dict_to_exam(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def _dict_to_exam(self, data: dict) -> ExamRecord:
        """Convert dictionary back to ExamRecord."""
        parts = {}
        for part_key, part_data in data.get("parts", {}).items():
            questions = [
                ExamQuestion(
                    number=q["number"],
                    question=q["question"],
                    depth=q.get("depth", 1),
                    asked=q.get("asked", False),
                    answer=q.get("answer", ""),
                    time_spent=q.get("time_spent", 0),
                )
                for q in part_data.get("questions", [])
            ]
            cue_card_data = part_data.get("cue_card")
            cue_card = None
            if cue_card_data:
                cue_card = ExamCueCard(
                    topic=cue_card_data.get("topic", ""),
                    bullet_points=cue_card_data.get("bullet_points", []),
                    asked=cue_card_data.get("asked", False),
                    answer=cue_card_data.get("answer", ""),
                    prep_time=cue_card_data.get("prep_time", 0),
                    speak_time=cue_card_data.get("speak_time", 0),
                )
            parts[part_key] = ExamPartData(
                part=ExamPart(part_data["part"]) if part_data.get("part") else ExamPart.PART1,
                questions=questions,
                cue_card=cue_card,
            )

        return ExamRecord(
            exam_id=data["exam_id"],
            topic=data["topic"],
            topic_file=data["topic_file"],
            started_at=data["started_at"],
            ended_at=data.get("ended_at", ""),
            state=ExamState(data.get("state", "idle")),
            current_part=ExamPart(data.get("current_part", "part1")),
            current_question_index=data.get("current_question_index", 0),
            parts=parts,
            final_score=data.get("final_score", {}),
        )

    def _parse_part1(self, content: str) -> list[ExamQuestion]:
        """Parse Part 1 questions from topic content."""
        questions = []
        in_part1 = False
        lines = content.split("\n")

        for line in lines:
            if "## Part 1" in line:
                in_part1 = True
                continue
            if in_part1 and line.startswith("## "):
                break
            if in_part1 and "|" in line and "Question" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 2:
                    try:
                        num = int(parts[1].strip())
                        question = parts[2].strip()
                        depth = int(parts[3].strip()) if len(parts) > 3 else 1
                        questions.append(ExamQuestion(
                            number=num,
                            question=question,
                            depth=depth,
                        ))
                    except (ValueError, IndexError):
                        continue

        return questions

    def _parse_part2_cue_card(self, content: str) -> ExamCueCard:
        """Parse Part 2 Cue Card from topic content."""
        in_part2 = False
        topic = ""
        bullet_points = []

        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "## Part 2" in line:
                in_part2 = True
                continue
            if in_part2 and line.startswith("## "):
                break
            if in_part2:
                # Only capture the first "Describe" line as topic, skip "Cue Card Asked"
                if "**Describe" in line and not topic:
                    topic = line.replace("**", "").replace("Describe", "").strip()
                    if not topic:
                        topic = "Describe a topic"
                elif line.strip().startswith("- "):
                    bullet_points.append(line.strip()[2:])
                elif line.strip().startswith("* "):
                    bullet_points.append(line.strip()[2:])

        return ExamCueCard(
            topic=topic or "Describe a topic",
            bullet_points=bullet_points,
        )

    def _parse_part3(self, content: str) -> list[ExamQuestion]:
        """Parse Part 3 questions from topic content."""
        questions = []
        in_part3 = False
        lines = content.split("\n")

        for line in lines:
            if "## Part 3" in line:
                in_part3 = True
                continue
            if in_part3 and line.startswith("## "):
                break
            if in_part3 and "|" in line and "Question" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 2:
                    try:
                        num = int(parts[1].strip())
                        question = parts[2].strip()
                        depth = int(parts[3].strip()) if len(parts) > 3 else 3
                        questions.append(ExamQuestion(
                            number=num,
                            question=question,
                            depth=depth,
                        ))
                    except (ValueError, IndexError):
                        continue

        return questions

    def get_current_question(self) -> ExamQuestion | None:
        """Get the current question based on state."""
        if not self._active_exam:
            return None

        exam = self._active_exam

        if exam.state == ExamState.PART1_QUESTIONS:
            part1 = exam.parts.get("part1")
            if part1 and exam.current_question_index < len(part1.questions):
                return part1.questions[exam.current_question_index]

        elif exam.state == ExamState.PART3_QUESTIONS:
            part3 = exam.parts.get("part3")
            if part3 and exam.current_question_index < len(part3.questions):
                return part3.questions[exam.current_question_index]

        return None

    def get_current_cue_card(self) -> ExamCueCard | None:
        """Get the current Part 2 cue card."""
        if not self._active_exam:
            return None

        if self._active_exam.state in [ExamState.PART2_CUE_CARD, ExamState.PART2_SPEAKING]:
            return self._active_exam.parts.get("part2", {}).cue_card

        return None

    def record_answer(self, answer: str, time_spent: int = 0) -> None:
        """Record user's answer to the current question."""
        if not self._active_exam:
            return

        exam = self._active_exam

        if exam.state == ExamState.PART1_QUESTIONS:
            part1 = exam.parts.get("part1")
            if part1 and exam.current_question_index < len(part1.questions):
                q = part1.questions[exam.current_question_index]
                q.answer = answer
                q.time_spent = time_spent
                q.asked = True

        elif exam.state == ExamState.PART3_QUESTIONS:
            part3 = exam.parts.get("part3")
            if part3 and exam.current_question_index < len(part3.questions):
                q = part3.questions[exam.current_question_index]
                q.answer = answer
                q.time_spent = time_spent
                q.asked = True

        elif exam.state == ExamState.PART2_SPEAKING:
            cue_card = exam.parts.get("part2", {}).cue_card
            if cue_card:
                cue_card.answer = answer
                cue_card.speak_time = time_spent

        # Save after recording answer
        self._save_exam(exam)

    def next_step(self) -> ExamState:
        """Advance to the next step in the exam."""
        if not self._active_exam:
            return ExamState.IDLE

        exam = self._active_exam

        # Part 1: Move to next question or to Part 2
        if exam.state == ExamState.PART1_QUESTIONS:
            exam.current_question_index += 1
            part1 = exam.parts.get("part1")
            if part1 and exam.current_question_index >= len(part1.questions):
                # Move to Part 2
                exam.state = ExamState.PART2_CUE_CARD
                exam.current_part = ExamPart.PART2
                exam.current_question_index = 0
            self._save_exam(exam)
            return exam.state

        # Part 2: Cue card shown, waiting for "start speaking"
        if exam.state == ExamState.PART2_CUE_CARD:
            exam.state = ExamState.PART2_SPEAKING
            self._save_exam(exam)
            return exam.state

        # Part 2: Speaking done, move to Part 3
        if exam.state == ExamState.PART2_SPEAKING:
            exam.state = ExamState.PART3_QUESTIONS
            exam.current_part = ExamPart.PART3
            exam.current_question_index = 0
            self._save_exam(exam)
            return exam.state

        # Part 3: Move to next question or complete
        if exam.state == ExamState.PART3_QUESTIONS:
            exam.current_question_index += 1
            part3 = exam.parts.get("part3")
            if part3 and exam.current_question_index >= len(part3.questions):
                exam.state = ExamState.COMPLETED
                exam.ended_at = datetime.utcnow().isoformat() + "Z"
            self._save_exam(exam)
            return exam.state

        self._save_exam(exam)
        return exam.state

    def get_active_exam(self) -> ExamRecord | None:
        """Get the currently active exam (loads from disk if not in memory)."""
        return self._active_exam

    def set_active_exam(self, exam: ExamRecord) -> None:
        """Set the active exam (used when loading by ID)."""
        self._active_exam = exam

    def get_timing(self, state: ExamState) -> tuple[int, int]:
        """Get (prep_time, answer_time) for a given state."""
        timing_map = {
            ExamState.PART1_QUESTIONS: (0, self.PART1_ANSWER_TIME),
            ExamState.PART2_CUE_CARD: (self.PART2_PREP_TIME, 0),
            ExamState.PART2_SPEAKING: (0, self.PART2_SPEAK_TIME),
            ExamState.PART3_QUESTIONS: (0, self.PART3_ANSWER_TIME),
        }
        return timing_map.get(state, (0, 0))

    def _save_exam(self, exam: ExamRecord) -> None:
        """Save exam record to file."""
        exam_file = self._exams_dir / f"{exam.exam_id}.json"
        exam_file.write_text(json.dumps(exam.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def list_exams(self) -> list[ExamRecord]:
        """List all saved exam records."""
        exams = []
        for exam_file in self._exams_dir.glob("*.json"):
            try:
                data = json.loads(exam_file.read_text(encoding="utf-8"))
                exam = self._dict_to_exam(data)
                exams.append(exam)
            except (json.JSONDecodeError, KeyError):
                continue
        return sorted(exams, key=lambda x: x.started_at, reverse=True)

    def end_exam(self) -> None:
        """End the current exam early."""
        if self._active_exam:
            self._active_exam.state = ExamState.COMPLETED
            self._active_exam.ended_at = datetime.utcnow().isoformat() + "Z"
            self._save_exam(self._active_exam)
        self._active_exam = None
