class ScoringService:
    def __init__(self, rules):
        self.rules = rules
        if any(type(v) is not int or v < 0 for v in rules.values()):
            raise ValueError('Scoring weights must be non-negative integers')

    def points(self, event, duplicate: bool, novel: bool, earned: int):
        if not event['attack_detected'] or duplicate or event['outcome'] in {'UNKNOWN', 'NOT_APPLICABLE'}:
            return 0
        base = self.rules.get(event['outcome'], 0)
        if base > 0:
            if event['risk_score'] >= 85:
                base += self.rules.get('sophisticated', 0)
            if novel:
                base += self.rules.get('novel', 0)
        return max(0, min(base, self.rules.get('hourly_cap', 300) - earned))
