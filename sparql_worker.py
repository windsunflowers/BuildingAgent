"""RDFLib process isolation with a separate session for each concurrent question."""
import multiprocessing
import threading
import atexit
from contextlib import contextmanager
from contextvars import ContextVar


def _execute(graph, query, display_limit):
    result = graph.query(query)
    if result.type == 'ASK':
        value = bool(result.askAnswer)
        return {'ask': True, 'value': value, 'rows': [{'ASK': value}], 'vars': ['ASK'], 'total': 1}
    rows, total = [], 0
    for row in result:
        total += 1
        if display_limit is None or len(rows) < display_limit:
            rows.append({str(v): str(row[v]) if row[v] is not None else None for v in result.vars})
    return {'ask': False, 'rows': rows, 'vars': [str(v) for v in result.vars], 'total': total}


def _worker(pipe, graph):
    try:
        while True:
            query, display_limit = pipe.recv()
            try:
                pipe.send(('ok', _execute(graph, query, display_limit)))
            except Exception as exc:
                pipe.send(('error', str(exc)))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        pipe.close()


class QueryWorker:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = self.pipe = self.graph = None

    def close(self):
        with self.lock:
            if self.process is not None:
                if self.process.is_alive():
                    self.process.terminate()
                self.process.join(timeout=1)
                if not self.process.is_alive():
                    self.process.close()
            if self.pipe is not None:
                self.pipe.close()
            self.process = self.pipe = self.graph = None

    def run(self, graph, query, display_limit, timeout):
        with self.lock:
            if self.graph is not graph or self.process is None or not self.process.is_alive():
                self.close()
                context = multiprocessing.get_context('spawn')
                parent, child = context.Pipe()
                self.process = context.Process(target=_worker, args=(child, graph), daemon=True)
                self.pipe, self.graph = parent, graph
                try:
                    self.process.start()
                except Exception:
                    self.process = None
                    parent.close()
                    self.pipe = self.graph = None
                    raise
                finally:
                    child.close()
            try:
                self.pipe.send((query, display_limit))
                if not self.pipe.poll(timeout):
                    self.close()
                    return 'timeout', None
                return self.pipe.recv()
            except (EOFError, BrokenPipeError, OSError) as exc:
                self.close()
                return 'error', str(exc)


_default_worker = QueryWorker()
_session = ContextVar('brickqa_query_worker', default=None)


@contextmanager
def isolated_query_session():
    worker = QueryWorker()
    token = _session.set(worker)
    try:
        yield worker
    finally:
        worker.close()
        _session.reset(token)


def run_isolated(graph, query, display_limit, timeout):
    return (_session.get() or _default_worker).run(graph, query, display_limit, timeout)


def close_worker():
    _default_worker.close()


atexit.register(close_worker)
