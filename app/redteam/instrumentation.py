"""Best-effort observation; never changes guardrails, responses, or exceptions."""
import logging
import time
from contextvars import ContextVar
from functools import wraps

from .storage import utc_now
from .telemetry import get_telemetry

logger = logging.getLogger(__name__)
observation = ContextVar('redteam_observation', default=None)
QUERY_PATHS = {'/api/v1/ask', '/api/v1/trial-ask', '/api/v1/demo', '/api/v1/ask-tts', '/api/v1/ask-stream'}


def capture(prompt, response=None, status=200):
    state = observation.get()
    if not state or state['recorded']:
        return
    state['recorded'] = True
    try:
        response = response if isinstance(response, dict) else {}
        get_telemetry().submit(
            prompt=prompt, response=response.get('answer', ''), session=state['session'],
            latency=(time.perf_counter()-state['start'])*1000,
            signals={'blocked': response.get('status') == 'blocked', 'error': status >= 400 and response.get('status') != 'blocked'},
            timings=state['timings'])
    except Exception:
        logger.warning('Red-team observation unavailable')


def observe_query(function):
    @wraps(function)
    def wrapped(self, data, *args, **kwargs):
        try:
            response, status = function(self, data, *args, **kwargs)
        except Exception:
            capture(data.get('message', ''), status=500)
            raise
        capture(data.get('message', ''), response, status)
        return response, status
    return wrapped


def observe_stage(name):
    """Timing for instrumented sync stages; missing stages remain null, never zero."""
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            state = observation.get()
            start = time.perf_counter()
            if state:
                state['timings'].setdefault(name + '_start', utc_now())
            try:
                return function(*args, **kwargs)
            finally:
                if state:
                    timings = state['timings']
                    timings[name + '_complete'] = utc_now()
                    timings[name + '_ms'] = timings.get(name + '_ms', 0) + round((time.perf_counter()-start)*1000, 2)
        return wrapped
    return decorator


class ArenaObservationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] not in QUERY_PATHS or scope['method'] not in {'GET', 'POST'}:
            return await self.app(scope, receive, send)
        from starlette.requests import Request
        from starlette.concurrency import run_in_threadpool
        request = Request(scope)
        token = None
        state = None
        try:
            telemetry = get_telemetry()
            supplied = request.headers.get('x-redteam-session') or request.cookies.get('arena_session')
            session = await run_in_threadpool(telemetry.store.session, supplied)
            if session is None:
                session = await run_in_threadpool(telemetry.store.latest_named_session)
            if session is None:
                session = await run_in_threadpool(telemetry.store.create_session)
                token = session.pop('session_token')
            state = {'session': session, 'start': time.perf_counter(), 'recorded': False,
                     'timings': {'request_received': utc_now()}}
        except Exception:
            logger.warning('Red-team session unavailable; chatbot continuing')
        context_token = observation.set(state)
        status = 500

        async def observed_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                if token:
                    secure = '; Secure' if scope.get('scheme') == 'https' else ''
                    message = dict(message, headers=list(message.get('headers', [])) + [
                        (b'set-cookie', f'arena_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400{secure}'.encode())])
            await send(message)
        try:
            await self.app(scope, receive, observed_send)
        finally:
            # Includes rejected/invalid requests and disconnected streams, without reading request bodies.
            if state and not state['recorded']:
                capture('', status=max(status, 400))
            observation.reset(context_token)
