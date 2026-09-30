import hashlib
import logging
import queue
import threading
import time
import unicodedata
import uuid
from functools import lru_cache

from .classification import AttackClassificationService, LLMSecurityClassifier, Classification
from .config import ArenaConfig
from .evaluation import AttackEvaluationService, Evaluation, ExactCanaryCriterion, EVALUATOR_VERSION
from .storage import TelemetryStore, utc_now

logger = logging.getLogger(__name__)
WITHHELD = 'Content withheld: public telemetry does not retain chat text.'


class TelemetryService:
    def __init__(self, config=None, classifier=None, evaluator=None):
        self.config = config or ArenaConfig()
        self.store = TelemetryStore(self.config)
        self.classifier = classifier or AttackClassificationService(LLMSecurityClassifier(self.config) if self.config.classifier_url else None)
        from .judge import PolicyJudge
        judge = PolicyJudge(self.config) if self.config.judge_url and self.config.policy_file else None
        self.evaluator = evaluator or AttackEvaluationService(
            [ExactCanaryCriterion(self.config.test_canary)] if self.config.test_canary else [], judge=judge)
        self.queue = queue.Queue(self.config.queue_size)
        self.dropped = 0
        self.failures = 0
        self.closed = False
        self.worker = threading.Thread(target=self._work, name='redteam-telemetry', daemon=True)
        self.worker.start()

    def submit(self, *, prompt, response, session, latency, signals=None, timings=None, simulated=False, event_id=None) -> bool:
        if self.closed:
            self.dropped += 1
            return False
        signals = dict(signals or {})
        signals['truncated'] = len(str(prompt)) > 16000 or len(str(response)) > 32000
        job = dict(prompt=str(prompt)[:16000], response=str(response)[:32000], session=session,
                   latency=latency, signals=signals or {}, timings=timings or {}, simulated=simulated,
                   event_id=event_id or str(uuid.uuid4()), timestamp=utc_now(), queued=time.perf_counter())
        try:
            self.queue.put_nowait(job)
            return True
        except queue.Full:
            self.dropped += 1
            logger.warning('Red-team telemetry queue full; event dropped')
            return False

    def _work(self):
        while True:
            job = self.queue.get()
            try:
                if job is None:
                    return
                self.record(**job)
            except Exception:
                self.failures += 1
                # Never log prompts, model output, credentials, or exception content.
                logger.warning('Red-team telemetry processing failed')
            finally:
                self.queue.task_done()

    def record(self, *, prompt, response, session, latency, signals, timings, simulated, event_id, timestamp, queued):
        start = time.perf_counter()
        classification_start = utc_now()
        classification = self.classifier.classify(prompt, signals)
        classified = time.perf_counter()
        classification_complete = utc_now()
        evaluation = self.evaluator.evaluate(classification, prompt, response, signals)
        if simulated and signals.get('simulation_outcome') in {'BLOCKED', 'DEFENDED', 'PARTIAL', 'SUCCESSFUL', 'UNKNOWN'}:
            evaluation = Evaluation(signals['simulation_outcome'], 'Synthetic scenario outcome; not evidence about the production chatbot.', 'simulation')
        if evaluation.outcome in {'SUCCESSFUL', 'PARTIAL'} and not classification.detected:
            classification = Classification('Other / Unknown Attack', 90, 'response', 'A response detector found a configured policy violation despite no input pattern match.')
        evaluated = time.perf_counter()
        timings = dict(timings, classification_ms=round((classified-start)*1000, 2),
                       evaluation_ms=round((evaluated-classified)*1000, 2),
                       queue_ms=round((start-queued)*1000, 2), evaluation_complete=utc_now(),
                       classification_start=classification_start, classification_complete=classification_complete,
                       retrieval_ms=timings.get('retrieval_ms'), generation_ms=timings.get('generation_ms'))
        event = {'schema_version': 2, 'evaluator_version': EVALUATOR_VERSION, 'scoring_version': 2,
                 'evaluation_source': evaluation.source, 'evaluation_status': evaluation.status,
                 'evaluation_confidence': evaluation.confidence, 'event_id': event_id, 'timestamp': timestamp, **session,
                 'prompt': WITHHELD, 'assistant_response': WITHHELD,
                 'attack_detected': classification.detected, 'attack_category': classification.category,
                 'severity': classification.severity, 'risk_score': classification.risk,
                 'classification_source': classification.source, 'classification_reason': classification.reason,
                 'outcome': evaluation.outcome, 'reason': evaluation.reason, 'criterion': evaluation.criterion,
                 'blocked': evaluation.outcome == 'BLOCKED',
                 'attack_success': True if evaluation.outcome == 'SUCCESSFUL' else None if evaluation.outcome == 'UNKNOWN' else False,
                 'response_time_ms': round(max(0, latency)), 'model': self.config.model_label,
                 'knowledge_container': 'Withheld', 'timings': timings, 'simulated': simulated}
        # Never persist session bearer credentials, including callers passing a creation result.
        event.pop('session_token', None)
        normalized = ' '.join(unicodedata.normalize('NFKC', prompt).casefold().split())
        # Salt per participant to prevent cross-participant dictionary correlation.
        fingerprint = hashlib.sha256((session['session_id'] + normalized).encode()).hexdigest()
        return self.store.save(event, fingerprint)

    def health(self):
        return {'queued': self.queue.qsize(), 'dropped': self.dropped, 'failed': self.failures,
                'classifier_failures': self.classifier.failures, 'evaluation_failures': self.evaluator.failures, 'worker_alive': self.worker.is_alive()}

    def close(self):
        self.closed = True
        self.queue.put(None)
        self.worker.join(timeout=10)
        if not self.worker.is_alive():
            self.store.close()


@lru_cache(maxsize=1)
def get_telemetry():
    return TelemetryService()
