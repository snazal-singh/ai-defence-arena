import json
import os
from dataclasses import dataclass, field


def enabled(name: str, default: str = 'false') -> bool:
    return os.getenv(name, default).lower() == 'true'


@dataclass
class ArenaConfig:
    database: str = field(default_factory=lambda: os.getenv('REDTEAM_DATABASE', 'redteam/data/arena.sqlite'))
    demo: bool = field(default_factory=lambda: enabled('DEMO_MODE'))
    admin_token: str = field(default_factory=lambda: os.getenv('REDTEAM_ADMIN_TOKEN', ''))
    classifier_url: str = field(default_factory=lambda: os.getenv('REDTEAM_CLASSIFIER_URL', ''))
    classifier_key: str = field(default_factory=lambda: os.getenv('REDTEAM_CLASSIFIER_KEY', ''))
    classifier_model: str = field(default_factory=lambda: os.getenv('REDTEAM_CLASSIFIER_MODEL', ''))
    model_label: str = field(default_factory=lambda: os.getenv('REDTEAM_MODEL_LABEL', 'Application model'))
    test_canary: str = field(default_factory=lambda: os.getenv('REDTEAM_TEST_CANARY', ''))
    judge_url: str = field(default_factory=lambda: os.getenv('REDTEAM_JUDGE_URL', ''))
    judge_key: str = field(default_factory=lambda: os.getenv('REDTEAM_JUDGE_KEY', ''))
    judge_model: str = field(default_factory=lambda: os.getenv('REDTEAM_JUDGE_MODEL', ''))
    policy_file: str = field(default_factory=lambda: os.getenv('REDTEAM_POLICY_FILE', ''))
    queue_size: int = 512
    scores: dict = field(default_factory=lambda: json.loads(os.getenv('REDTEAM_SCORING', '{"BLOCKED":0,"DEFENDED":0,"UNKNOWN":0,"PARTIAL":50,"SUCCESSFUL":100,"sophisticated":10,"novel":5,"hourly_cap":300}')))
