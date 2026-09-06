from enum import Enum


class DocumentType(str, Enum):
    EMAIL = "email"
    PDF = "pdf"
    NOTICE = "notice"
    OTHER = "other"


class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    REJECTED = "rejected"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionType(str, Enum):
    REMINDER = "reminder"
    DRAFT_EMAIL = "draft_email"
    REQUEST_INFO = "request_info"
    ESCALATION = "escalation"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class GoalStatus(str, Enum):
    ACTIVE = "active"
    AT_RISK = "at_risk"
    COMPLETED = "completed"
    ABANDONED = "abandoned"