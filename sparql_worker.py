"""RDFLib process isolation with a separate session for each concurrent question."""
import multiprocessing
import threading
import atexit
import os
from contextlib import contextmanager
from contextvars import ContextVar


_spawn_lock = threading.Lock()
_NUMERICAL_THREADS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
                      'NUMEXPR_NUM_THREADS')


def _start_query_process(process):
    # Windows spawn imports the main application (and pandas/numpy) before
    # entering _worker. BLAS otherwise allocates a CPU-sized pool per question,
    # even though RDFLib does not use it. Limit only the child's inherited env;
    # restore the user's parent settings, including explicitly configured ones.
    with _spawn_lock:
        previous = {name: os.environ.get(name) for name in _NUMERICAL_THREADS}
        try:
            for name in _NUMERICAL_THREADS:
                os.environ[name] = '1'
            process.start()
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _execute(graph, query, display_limit, include_bindings=False):
    result = graph.query(query)
    if result.type == 'ASK':
        value = bool(result.askAnswer)
        return {'ask': True, 'value': value, 'rows': [{'ASK': value}], 'vars': ['ASK'], 'total': 1}
    rows, preview, bindings, total = [], [], [], 0
    for row in result:
        total += 1
        if display_limit is None or len(rows) < display_limit:
            rows.append({str(v): str(row[v]) if row[v] is not None else None for v in result.vars})
            if include_bindings or len(preview) < 10:
                binding = _binding_row(row, result.vars)
                if include_bindings:
                    bindings.append(binding)
                if len(preview) < 10:
                    preview.append(binding)
    data = {'ask': False, 'rows': rows, 'vars': [str(v) for v in result.vars],
            'total': total, 'bindings_preview': preview}
    if include_bindings:
        data['bindings'] = bindings
    return data


def _binding_row(row, variables):
    """SPARQL JSON terms from real RDF terms, before string conversion."""
    from rdflib import URIRef, Literal, BNode
    binding = {}
    for variable in variables:
        term = row[variable]
        if term is None:
            continue  # An unbound variable has no SPARQL JSON binding.
        if isinstance(term, URIRef):
            value = {'type':'uri', 'value':str(term)}
        elif isinstance(term, BNode):
            value = {'type':'bnode', 'value':str(term)}
        elif isinstance(term, Literal):
            value = {'type':'literal', 'value':str(term)}
            if term.datatype:
                value['datatype'] = str(term.datatype)
            if term.language:
                value['xml:lang'] = term.language
        else:
            value = {}  # Preserve the provided formatter's unknown-term behavior.
        binding[str(variable)] = value
    return binding


def _worker(pipe, graph):
    try:
        while True:
            request = pipe.recv()
            query, display_limit = request[:2]
            include_bindings = request[2] if len(request) > 2 else False
            try:
                pipe.send(('ok', _execute(graph, query, display_limit, include_bindings)))
            except Exception as exc:
                pipe.send(('error', str(exc) or f'{type(exc).__name__}: no exception message'))
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

    def run(self, graph, query, display_limit, timeout, include_bindings=False):
        with self.lock:
            if self.graph is not graph or self.process is None or not self.process.is_alive():
                self.close()
                context = multiprocessing.get_context('spawn')
                parent, child = context.Pipe()
                self.process = context.Process(target=_worker, args=(child, graph), daemon=True)
                self.pipe, self.graph = parent, graph
                try:
                    _start_query_process(self.process)
                except Exception:
                    self.process = None
                    parent.close()
                    self.pipe = self.graph = None
                    raise
                finally:
                    child.close()
            try:
                self.pipe.send((query, display_limit, include_bindings))
                if not self.pipe.poll(timeout):
                    self.close()
                    return 'timeout', None
                return self.pipe.recv()
            except (EOFError, BrokenPipeError, OSError) as exc:
                # EOFError has an empty str(); retain evidence before close()
                # terminates/releases the process. Never call this a syntax error.
                message = (f'SPARQL worker transport failure ({type(exc).__name__}): '
                           f'{str(exc) or "no exception message"}; '
                           f'pid={self.process.pid}; exitcode={self.process.exitcode}')
                self.close()
                return 'worker_error', message


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


def run_isolated(graph, query, display_limit, timeout, include_bindings=False):
    return (_session.get() or _default_worker).run(graph, query, display_limit, timeout, include_bindings)


def close_worker():
    _default_worker.close()


atexit.register(close_worker)
