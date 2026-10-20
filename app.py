"""BrickQA local application: grounded queries, paper agent, graph exploration and evaluation."""

import os
import sys
import json
import time
import threading
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

# --- Snappy cooldown defaults for the UI (user can override to restore fidelity) ---
os.environ.setdefault("BRICK_COOLDOWN_PRE", "0")
os.environ.setdefault("BRICK_COOLDOWN_POST", "0")
os.environ.setdefault("BRICK_DECOMP_COOLDOWN", "0")

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)  # so brick_agent finds prompts/ relatively
sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from model_settings import get_registry
from typing import Literal as Choice
from uuid import uuid4
from collections import Counter
import csv
import io
from evaluation_metrics import METRIC_PROTOCOL, metric_reference, summarize_results, norm_rows, extract_predicates, f1
from evaluation_runner import evaluate_question
from implementation_policy import policy_metadata, record_event, evaluation_timeout, EVALUATION_ALIGNMENT
import uvicorn

from brick_agent import BrickAgent, BrickSparqlQuery
from brick_utils import SparqlExecutionStatus, BrickGraph, get_all_sensor_types, execute_sparql, BRICK_PREFIXES, query_graph, local_name, search_brick, get_brick_entity
from rdflib import URIRef, Literal, RDF, RDFS
import re

app = FastAPI(title="BrickQA", version="2.0")

class AskRequest(BaseModel):
    model_config = {'extra':'forbid'}
    question: str = Field(min_length=1, max_length=4000)
    context: Choice[0, 100, 5000] = 0
    context_ttl: Optional[str] = None
    language: Choice['zh', 'en'] = 'zh'

class LoadRequest(BaseModel):
    model_config = {'extra':'forbid'}
    ttl: str = Field(min_length=1)
    description: Optional[str] = None
    csv: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_rows: int = Field(default=100, ge=1, le=20000)

class SparqlRequest(BaseModel):
    query: str = Field(min_length=1, max_length=50000)
    limit: int = Field(default=200, ge=1, le=5000)

class EvalRequest(BaseModel):
    model_config = {'extra':'forbid'}
    benchmark: str = 'benchmark_sample.jsonl'
    context: Choice[0, 100, 5000] = 0
    context_ttl: Optional[str] = None
    language: Choice['zh', 'en'] = 'en'
    workers: int = Field(default=3, ge=1, le=8, strict=True)


class ModelSelectionRequest(BaseModel):
    model_config = {'extra':'forbid'}
    profile_id: Choice['qwen', 'gemini-2.5-flash']
    api_key: Optional[SecretStr] = None


PROMPTS_DIR = BASE_DIR / "prompts"
UI_DIR = BASE_DIR / "ui"
app.mount('/ui', StaticFiles(directory=UI_DIR), name='ui')
DATA_DIR = BASE_DIR / "data"
DEFAULT_TTL = DATA_DIR / "buildings" / "bldg11.ttl"
if not DEFAULT_TTL.exists():
    DEFAULT_TTL = PROMPTS_DIR / "dflexlibs_multizone_sample_5000.ttl"

# --- Global state (single-user, single active run) ---
agent: Optional[BrickAgent] = None
graph_meta = {"building": None, "triples": 0, "sensors": 0, "loaded_at": None}
tasks: dict = {}                 # task_id -> dict(state, status, final, error, question)
_active_tid: Optional[str] = None
_lock = threading.RLock()
_loading = False

# --- Evaluation (gold-answer benchmark) state ---
eval_tasks: dict = {}             # eval_task_id -> dict(status, summary, results, error)
# An optional explicit deadline. Upstream defaults to no whole-question timer;
# Individual model requests keep their own timeouts.
EVAL_PER_QUESTION_TIMEOUT = os.getenv("EVAL_PER_QUESTION_TIMEOUT")
_eval_running = False
_eval_cancel_events = {}          # Runtime-only events; never serialized in reports.
_eval_execution_events = {}       # task -> {question index: interruption event}
_eval_agents = {}                 # Runtime-only Agents, isolated per question.


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _list_buildings():
    buildings = []
    files = sorted((DATA_DIR / 'buildings').glob('*.ttl')) + sorted(PROMPTS_DIR.glob('*.ttl'))
    for t in files:
        if t.stem == "brick":  # ontology, not a building
            continue
        desc = PROMPTS_DIR / f"{t.stem}_description.txt"
        if not desc.exists():
            desc = PROMPTS_DIR / f"{t.stem.replace('_100', '_5000')}_description.txt"
        if not desc.exists():
            desc = PROMPTS_DIR / f"{t.stem}_sample_5000_description.txt"
        buildings.append({
            "id": t.stem,
            "ttl": str(t),
            "description": str(desc) if desc.exists() else None,
            "sample": "sample" in t.stem,
        })
    csvs = [str(c) for c in sorted(PROMPTS_DIR.glob("*.csv"))]
    return buildings, csvs


def _prepare_ttl_context(req):
    """Snapshot an existing project TTL without changing the execution graph."""
    if not req.context_ttl:
        return None
    if req.context:
        raise HTTPException(status_code=400, detail='TTL 文件与旧版上下文数量不能同时选择。')
    path = (BASE_DIR / req.context_ttl).resolve()
    allowed = {Path(b['ttl']).resolve() for b in _list_buildings()[0]}
    if path not in allowed or not path.is_file():
        raise HTTPException(status_code=400, detail='请选择列表中已有的项目 TTL 文件。')
    building_id = lambda name: re.sub(r'_sample_\d+$', '', Path(name).stem)
    if building_id(path.name) != building_id(graph_meta.get('ttl') or ''):
        raise HTTPException(status_code=400, detail='上下文 TTL 必须属于当前已加载的建筑。')
    raw = path.read_bytes()
    content = raw.decode('utf-8-sig')
    from rdflib import Graph
    try:
        triples = len(Graph().parse(data=content, format='turtle'))
    except Exception as exc:
        raise HTTPException(status_code=400, detail='上下文 TTL 解析失败。') from exc
    return {'content': content, 'raw': raw, 'file': path.relative_to(BASE_DIR).as_posix(),
            'sha256': hashlib.sha256(raw).hexdigest(), 'triples': triples}


def _context_metadata(snapshot):
    return {key: snapshot[key] for key in ('file', 'sha256', 'triples')} if snapshot else None


def _serialize_decomposition(decomp):
    if decomp is None:
        return None
    return {
        "sensors": [
            {"mention": s.mention, "sensor_id": s.sensor_id, "description": s.description}
            for s in decomp.sensors
        ],
        "sensor_count": decomp.sensor_count,
        "temporal": {
            "has_constraint": decomp.temporal.has_constraint,
            "type": decomp.temporal.type,
            "details": decomp.temporal.details,
        },
        "aggregation": {
            "required": decomp.aggregation.required,
            "operations": decomp.aggregation.operations,
        },
        "query_intent": decomp.query_intent,
    }


def _cap(text, limit=8000):
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + f"\n…(truncated, {len(text)} chars total)"


def _serialize_state(state, status, error=None):
    if state is None:
        return {
            "status": status, "question": "", "actions": [], "decomposition": None,
            "generated_sparqls": [], "final_sparql": None, "tokens": {}, "error": error,
        }
    actions = [
        {
            "step": i + 1,
            "thought": a.thought,
            "action_name": a.action_name,
            "action_argument": a.action_argument,
            "observation": _cap(a.observation),
            "diagnostics": a.diagnostics,
        }
        for i, a in enumerate(state.actions)
    ]
    gens = [
        {
            "sparql": q.sparql,
            "status": q.execution_status.name if q.execution_status else None,
            "num_results": len(q.execution_result) if q.execution_result else 0,
            "diagnostic_warnings": q.diagnostic_warnings,
        }
        for q in state.generated_sparqls
    ]
    final = None
    if state.final_sparql:
        fs = state.final_sparql
        final = {
            "sparql": fs.sparql,
            "status": fs.execution_status.name if fs.execution_status else None,
            "num_results": len(fs.execution_result) if fs.execution_result else 0,
            "results": fs.execution_result[:100] if fs.execution_result else [],
            "warnings": fs.validation_warnings, "error": fs.error,
            "diagnostic_warnings": fs.diagnostic_warnings,
        }
    tokens = {
        "prompt": state.prompt_tokens,
        "completion": state.completion_tokens,
        "total": state.total_tokens,
    }
    return {
        "status": status,
        "question": state.question,
        "model_configuration": state.model_configuration, "response_models":state.response_models,
        "actions": actions,
        "decomposition": _serialize_decomposition(state.decomposition),
        "generated_sparqls": gens,
        "final_sparql": final,
        "tokens": tokens,
        "error": error,
        "phase": state.phase, "mode": state.mode, "warnings": state.warnings,
        "language": state.language,
        "implementation_mode": state.implementation_mode,
        "stop_reason": state.stop_reason,
    }


def _do_load(ttl, description=None, csv_file=None, start_date=None, end_date=None, max_rows=100):
    """Build in isolation, publish atomically; failed loads keep the previous building."""
    global agent, graph_meta
    ttl = Path(ttl).expanduser().resolve()
    if not ttl.is_file() or ttl.suffix.lower() != '.ttl':
        raise ValueError(f'TTL 文件不存在或格式不正确：{ttl}')
    for path, label in ((description, '描述'), (csv_file, 'CSV')):
        if path and not Path(path).is_file():
            raise ValueError(f'{label} 文件不存在：{path}')
    if not description:
        candidate_desc = ttl.with_name(ttl.stem.replace('_100', '_5000') + '_description.txt')
        if candidate_desc.is_file():
            description = str(candidate_desc)
        elif (PROMPTS_DIR / (ttl.stem + '_sample_5000_description.txt')).is_file():
            description = str(PROMPTS_DIR / (ttl.stem + '_sample_5000_description.txt'))
    candidate = object.__new__(BrickGraph)
    candidate._graph = None
    candidate.initialize(ttl_file=str(ttl))
    if csv_file:
        candidate.add_timeseries_data(csv_file, int(max_rows), start_date, end_date)
    a = BrickAgent(use_decomposer=True, use_temporal_handler=True,
                   schema_description_file=description)
    a.brick_graph = candidate
    a._extract_date_metadata()
    sensor_classes = {URIRef('https://brickschema.org/schema/Brick#Sensor')}
    pending = list(sensor_classes)
    while pending:
        for child in candidate.get_graph().subjects(RDFS.subClassOf, pending.pop()):
            if child not in sensor_classes:
                sensor_classes.add(child)
                pending.append(child)
    sensors = {s for s, t in candidate.source_graph.subject_objects(RDF.type) if t in sensor_classes}
    warnings = list(getattr(candidate, 'data_warnings', []))
    if 'sample' in ttl.stem:
        warnings.append('当前 TTL 是采样图谱，结果仅覆盖已加载数据；完整建筑查询请加载完整 TTL。')
    ts = candidate.timeseries_meta
    if ts.get('truncated'):
        warnings.append(f'时序仅加载最近 {ts["rows"]} / {ts["available_rows"]} 行，请按需要调整日期或行数。')
    if ts.get('unmatched_columns'):
        warnings.append('以下 CSV 列未关联到测点：' + ', '.join(ts['unmatched_columns']))
    record_event(candidate, tool='graph_load', status='ok', ttl=str(ttl),
                 shared_runtime='Existing TTL repair, ontology merge and SPARQL runner retained; author evaluation acceptance is the only strategy')
    meta = {"building": ttl.stem, "ttl": str(ttl), "csv": csv_file,
            "triples": candidate.source_triples, "total_triples": len(candidate.get_graph()),
            "sensors": len(sensors), "sample": 'sample' in ttl.stem,
            "timeseries": ts, "warnings": warnings, "loaded_at": datetime.now().isoformat()}
    meta.update(implementation_mode='upstream', method_policy=policy_metadata(candidate))
    BrickGraph._instance = candidate
    search_brick.cache_clear()
    get_brick_entity.cache_clear()
    agent, graph_meta = a, meta
    return meta


@app.get('/api/examples')
def examples(language: Choice['zh', 'en'] = 'zh'):
    en = language == 'en'
    questions = (['What temperature sensors are in the building?', 'List all equipment', 'How many sensors are in the building?']
                 if en else ['楼里有哪些温度传感器？', '有哪些设备？', '有多少传感器？'])
    if agent:
        source = BrickGraph().source_graph
        for cls in ('AHU', 'VAV', 'FCU', 'Air_Handling_Unit'):
            candidates = sorted({s for s, t in source.subject_objects(RDF.type)
                                 if local_name(t) == cls and isinstance(s, URIRef)}, key=str)
            if candidates:
                identifier = local_name(candidates[0])
                questions.append(f'What points are associated with {identifier}?' if en else f'{identifier}关联了哪些测点？')
                break
    if graph_meta.get('timeseries', {}).get('rows'):
        questions.extend(['What is the latest room temperature?', 'Find the maximum outdoor air temperature observed during the last 24 hours.']
                         if en else ['室温最新值', '室外温度最近24小时的最大值'])
    else:
        questions.extend(['List all HVAC zones', 'Which equipment has zone air temperature setpoints?']
                         if en else ['有哪些HVAC区域？', '哪些设备带有区域空气温度设定值？'])
    return {'questions': questions}

def _run_task(tid, question, runner):
    global _active_tid
    timer = threading.Timer(float(os.getenv('BRICK_QUERY_TIMEOUT', '240')), runner.cancel_event.set)
    timer.daemon = True
    timer.start()
    try:
        state, final = runner.run(question, verbose=False)
        state.warnings.extend(tasks[tid]['graph'].get('warnings', []))
        tasks[tid].update(state=state, final=final, status='done')
    except Exception as exc:
        tasks[tid]['state'] = getattr(runner, '_current_state', None)
        tasks[tid]['status'] = 'cancelled' if runner.cancel_event.is_set() else 'error'
        tasks[tid]['error'] = str(exc)
    finally:
        timer.cancel()
        tasks[tid]['elapsed_seconds'] = round(time.monotonic() - tasks[tid]['started_at'], 2)
        with _lock:
            if _active_tid == tid:
                _active_tid = None




# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.on_event("startup")
def _startup():
    # Auto-load a small default building so the UI is usable immediately.
    try:
        if DEFAULT_TTL.exists():
            _do_load(str(DEFAULT_TTL), description=None)
            print(f"[startup] Auto-loaded default building: {DEFAULT_TTL.stem}")
    except Exception as e:
        print(f"[startup] Auto-load failed (you can load one manually): {e}")


@app.get("/")
def index():
    return FileResponse(UI_DIR / "index.html")


@app.get("/api/buildings")
def buildings():
    b, c = _list_buildings()
    return {"buildings": b, "csvs": c}


@app.get("/api/status")
def status():
    model = get_registry().current()
    active_eval = next((tid for tid, run in reversed(list(eval_tasks.items())) if run['status'] == 'running'), None)
    return {
        "evaluation_alignment": EVALUATION_ALIGNMENT,
        "evaluation_cancellation": True,
        "evaluation_concurrency": {"default": 3, "maximum": 8},
        "graph": graph_meta,
        "running": _active_tid is not None,
        "active_task_id": _active_tid, "evaluating": _eval_running, "loading": _loading,
        "active_eval_task_id": active_eval,
        "llm_ready": bool(model.api_key),
        "model": model.model, "model_profile":model.profile_id, "model_provider":model.provider,
        "base_url": model.base_url,
    }


@app.get('/api/models')
def models():
    return get_registry().catalog()


@app.post('/api/models/select')
def select_model(req: ModelSelectionRequest):
    with _lock:
        if _active_tid or _eval_running or _loading:
            raise HTTPException(status_code=409, detail='A query, evaluation or load is running. Change models after it finishes.')
        try:
            selected = get_registry().activate(req.profile_id, req.api_key.get_secret_value() if req.api_key else None)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        if agent and agent.decomposer:
            agent.decomposer.model_name = selected['model']
        return selected


@app.post('/api/models/test')
def test_model_connection():
    global _loading
    with _lock:
        if _active_tid or _eval_running or _loading:
            raise HTTPException(status_code=409, detail='Another task is running')
        _loading = True
    try:
        from llm_client import get_client, close_thread_client
        client = get_client()
        text = client.generate_text('Reply with exactly OK.', max_retries=1, max_tokens=2048)
        return {'ok':True, 'model':client.model, 'response_model':client.last_response_model,
                'provider':client.provider, 'usage':client.last_usage, 'response':text[:100]}
    except Exception as exc:
        # Never echo request objects, headers or SDK error bodies to the UI.
        message = str(exc)
        for key in get_registry().keys.values():
            if key:
                message = message.replace(key, '[redacted]')
        raise HTTPException(status_code=400, detail=message) from None
    finally:
        close_thread_client()
        with _lock:
            _loading = False


@app.post("/api/load")
def load(req: LoadRequest):
    global _loading
    with _lock:
        if _active_tid or _eval_running or _loading:
            raise HTTPException(status_code=409, detail='查询或评测进行中，请完成后再切换建筑')
        _loading = True
    try:
        return _do_load(req.ttl, req.description, req.csv, req.start_date, req.end_date, req.max_rows)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        with _lock:
            _loading = False


@app.post("/api/ask")
def ask(req: AskRequest):
    global _active_tid
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail='请输入问题')
    with _lock:
        if agent is None:
            raise HTTPException(status_code=400, detail='请先加载建筑')
        if _eval_running or _active_tid or _loading:
            raise HTTPException(status_code=409, detail='另一项任务进行中，请稍候')
        tid = 't' + uuid4().hex
        runner = agent
        context_snapshot = _prepare_ttl_context(req)
        runner.language = req.language
        if context_snapshot is not None:
            runner.ttl_schema_content = context_snapshot['content']
        else:
            runner.set_schema_context(req.context)
        runner.cancel_event.clear()
        runner._current_state = None
        while len(tasks) >= 100:
            tasks.pop(next(iter(tasks)))
        tasks[tid] = {"status": "running", "question": question, "state": None,
                      "final": None, "error": None, "runner": runner, "mode": "paper", "language": req.language,
                      "start": datetime.now().isoformat(), "started_at": time.monotonic(),
                      "graph": dict(graph_meta)}
        tasks[tid]['implementation_mode'] = runner.implementation_mode
        tasks[tid]['context_ttl'] = _context_metadata(context_snapshot)
        _active_tid = tid
    threading.Thread(target=_run_task, args=(tid, question, runner), daemon=True).start()
    return {"task_id": tid}


@app.get("/api/task/{tid}")
def task(tid: str):
    if tid not in tasks:
        raise HTTPException(status_code=404, detail='记录不存在（服务重启后历史会清空）')
    info = tasks[tid]
    state = info.get('state')
    if info['status'] == 'running':
        state = getattr(info['runner'], '_current_state', None)
    data = _serialize_state(state, info['status'], info.get('error'))
    data.update(question=info['question'], task_id=tid, graph=info['graph'], language=info.get('language', 'zh'),
                context_ttl=info.get('context_ttl'),
                implementation_mode=info.get('implementation_mode', 'legacy'),
                elapsed_seconds=info.get('elapsed_seconds', round(time.monotonic() - info['started_at'], 2)))
    return data


@app.post("/api/task/{tid}/cancel")
def cancel_task(tid: str):
    if tid not in tasks:
        raise HTTPException(status_code=404, detail='记录不存在')
    if tasks[tid]['status'] == 'running':
        tasks[tid]['runner'].cancel_event.set()
    return {"status": tasks[tid]['status'], "message": '已请求取消；当前网络请求结束后释放任务'}


@app.get("/api/task/{tid}/export")
def export_task(tid: str):
    info = tasks.get(tid)
    if not info or info['status'] != 'done' or not info.get('final'):
        raise HTTPException(status_code=400, detail='查询完成后才能导出')
    rows = info['final'].execution_result or []
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
    writer.writeheader()
    writer.writerows(rows)
    return Response(stream.getvalue().encode('utf-8-sig'), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="brickqa-{tid}.csv"'})


@app.get('/api/task/{tid}/results')
def task_results(tid: str, offset: int = 0, limit: int = 100):
    info = tasks.get(tid)
    if not info or not info.get('final'):
        raise HTTPException(status_code=404, detail='查询结果不存在')
    if offset < 0 or not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail='分页参数无效')
    rows = info['final'].execution_result or []
    return {'rows': rows[offset:offset+limit], 'total': len(rows), 'offset': offset}




@app.get("/api/tasks")
def tasks_list():
    return [
        {"task_id": k, "question": v["question"], "status": v["status"], "building": v["graph"]["building"],
         "implementation_mode": v.get('implementation_mode', 'legacy')}
        for k, v in sorted(tasks.items(), reverse=True)
    ]


# --------------------------------------------------------------------------- #
# Exploration helpers (namespace-agnostic — bldg11 uses ns2:, not bldg:)
# --------------------------------------------------------------------------- #
def _esc(s):
    """Sanitize a user term before embedding into a SPARQL string."""
    return str(s).replace("\\", "").replace('"', " ").replace("\n", " ").replace("\r", " ")


def short_name(uri):
    s = str(uri)
    return s.split("#")[-1] if "#" in s else s.rstrip("/").split("/")[-1]


def _graph():
    return BrickGraph().get_graph()


def _search_entities(term, limit=12):
    return [{"id": r['id'], "uri": r['uri'], "types": r['type'].split(', '), "label": r['label']}
            for r in search_brick(term, max(1, min(limit, 200)))]

def _resolve_entity(ident):
    result = get_brick_entity(ident)
    return URIRef(result['uri']) if result.get('uri') and not result.get('error') else None

def _entity_detail(ident):
    g = _graph()
    uri = _resolve_entity(ident)
    if uri is None:
        return {"error": f"未找到实体: {ident}"}
    types = [short_name(o) for o in g.objects(uri, RDF.type)]
    props = {}
    for p, o in g.predicate_objects(uri):
        pname = short_name(p)
        if isinstance(o, Literal):
            props.setdefault(pname, []).append({
                "value": str(o), "type": "literal",
                "datatype": str(o.datatype) if o.datatype else None,
            })
        else:
            props.setdefault(pname, []).append({
                "value": short_name(o), "uri": str(o), "type": "uri",
            })
    incoming = []
    for s, p in g.subject_predicates(uri):
        incoming.append({"subject": short_name(s), "subject_uri": str(s), "pred": short_name(p)})
    return {
        "uri": str(uri), "types": types, "properties": props,
        "incoming": incoming[:60],
    }


def _list_classes(limit=80):
    g = BrickGraph().source_graph
    counts = Counter(t for s, t in g.subject_objects(RDF.type)
                     if isinstance(s, URIRef) and str(t).startswith('https://brickschema.org/schema/Brick#')
                     and not str(s).startswith(('https://brickschema.org/schema/', 'https://w3id.org/rec#')))
    return [{"type": short_name(t), "uri": str(t), "count": count}
            for t, count in counts.most_common(limit)]


def _list_relations(limit=80):
    g = BrickGraph().source_graph
    counts = Counter(p for s, p, o in g
                     if isinstance(s, URIRef)
                     and not str(s).startswith(('https://brickschema.org/schema/', 'https://w3id.org/rec#')))
    return [{"pred": short_name(p), "uri": str(p), "count": count}
            for p, count in counts.most_common(limit)]


def _resolve_pred(pred):
    g = _graph()
    if pred.startswith("http"):
        return URIRef(pred)
    if ":" in pred:
        pref, local = pred.split(":", 1)
        ns = {p: u for p, u in g.namespaces() if p}
        if pref in ns:
            return URIRef(str(ns[pref]) + local)
    return URIRef(pred)


def _relation_instances(pred, limit=50):
    g = _graph()
    preduri = _resolve_pred(pred)
    out = []
    for subject, obj in g.subject_objects(preduri):
        if isinstance(obj, Literal):
            out.append({"subject": short_name(subject), "subject_uri": str(subject),
                        "object": str(obj), "object_uri": None})
        else:
            out.append({"subject": short_name(subject), "subject_uri": str(subject),
                        "object": short_name(obj), "object_uri": str(obj)})
        if len(out) >= max(1, min(limit, 200)):
            break
    return out


def _safe_sparql(query, limit=200, timeout=30):
    data, status, error = query_graph(query, display_limit=limit, timeout=timeout)
    if data:
        data['ok'] = True
    return data, error


_norm_rows = norm_rows
_extract_predicates = extract_predicates
_f1 = f1



def _read_benchmark(path):
    items = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    if not items:
        raise ValueError('基准文件没有问题。')
    if any(not isinstance(item, dict) or not item.get('question') for item in items):
        raise ValueError('基准问题格式无效。')
    return items


def _validate_benchmark_graph(items):
    expected = {(BASE_DIR / item['ttl']).resolve() for item in items if item.get('ttl')}
    loaded = Path(graph_meta.get('ttl') or '').resolve()
    if expected and expected != {loaded}:
        names = ', '.join(sorted(path.stem for path in expected))
        raise ValueError('基准与当前建筑不匹配，请先加载对应完整图谱：' + names)


def _run_eval(tid, bench_path, context=0, language='en', context_snapshot=None, workers=1):
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    from sparql_worker import isolated_query_session
    from llm_client import close_thread_client
    global _eval_running
    a = agent
    previous = (a.use_temporal_handler, a.use_aggregation, a.ttl_schema_content, a.language, a.cancel_event)
    completed, interrupted, active = {}, {}, {}
    target = BASE_DIR / 'output' / 'evaluations' / tid / 'report.json'
    run = eval_tasks[tid]
    pool = None
    with _lock:
        cancel_event = _eval_cancel_events.setdefault(tid, threading.Event())
        _eval_execution_events[tid] = {}
        _eval_agents[tid] = {}
    def save():
        with _lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(target)
    def update_active():
        run['active_questions'] = [dict(active[i]) for i in sorted(active)]
        run['current'] = run['active_questions'][0] if active else None
    def evaluate(index, item):
        question_agent = a.fork_evaluation() if workers > 1 else a
        question_agent.cancel_event = threading.Event()
        question_agent._current_state = None
        with _lock:
            _eval_agents[tid][index] = question_agent
            _eval_execution_events[tid][index] = question_agent.cancel_event
            if cancel_event.is_set():
                question_agent.cancel_event.set()
            active[index] = {'index': index + 1, 'total': len(items), 'question': item['question'],
                             'query_id': item.get('query_id'), 'stage': 'gold', 'started_at': time.time()}
            update_active()
        def progress(stage):
            with _lock:
                active[index]['stage'] = stage
                update_active()
                save()
        try:
            with isolated_query_session():
                record = evaluate_question(question_agent, {**item, 'ttl': item.get('ttl') or graph_meta['ttl']},
                                           timeout=timeout, on_progress=progress, cancel_event=cancel_event)
                record.update(question_index=index + 1, prompt_log=question_agent.log_file)
                return record
        finally:
            try:
                close_thread_client()
            finally:
                with _lock:
                    active.pop(index, None)
                    _eval_agents[tid].pop(index, None)
                    _eval_execution_events[tid].pop(index, None)
                    update_active()
    try:
        if not 1 <= workers <= 8:
            raise ValueError('Evaluation workers must be between 1 and 8')
        run.update(run_id=tid, metric_protocol=METRIC_PROTOCOL, report_path=str(target))
        run['metric_reference'] = metric_reference()
        timeout = evaluation_timeout(EVAL_PER_QUESTION_TIMEOUT)
        run['configuration'] = {'language': language, 'context': context, 'mode': 'paper',
                                'workers': workers, 'scheduling': 'bounded_thread_pool',
                                'method_policy': policy_metadata(a.brick_graph),
                                'implementation_mode': a.implementation_mode,
                                'context_ttl': _context_metadata(context_snapshot),
                                'context_mode': 'existing_ttl' if context_snapshot else ('sampled' if context else 'NoKG'),
                                'model': os.getenv('LLM_MODEL', 'qwen-plus'),
                                'model_configuration':get_registry().current().public(),
                                'benchmark': str(bench_path), 'graph': dict(graph_meta),
                                'temporal': False, 'operations': False, 'timeout': timeout}
        items = _read_benchmark(bench_path)
        _validate_benchmark_graph(items)
        a.use_temporal_handler = False
        a.use_aggregation = False
        a.language = language
        if context_snapshot is not None:
            a.ttl_schema_content = context_snapshot['content']
            target.parent.mkdir(parents=True, exist_ok=True)
            (target.parent / 'context.ttl').write_bytes(context_snapshot['raw'])
        else:
            a.set_schema_context(context)
        run['summary'] = summarize_results([], total=len(items))
        save()
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='brickqa-eval')
        pending, next_index = {}, 0
        while pending or (next_index < len(items) and not cancel_event.is_set()):
            with _lock:
                while len(pending) < workers and next_index < len(items) and not cancel_event.is_set():
                    pending[pool.submit(evaluate, next_index, items[next_index])] = next_index
                    next_index += 1
            if not pending:
                break
            finished, _ = wait(pending, timeout=.25, return_when=FIRST_COMPLETED)
            for future in sorted(finished, key=lambda f: pending[f]):
                index = pending.pop(future)
                record = future.result()
                with _lock:
                    if record.get('status') == 'cancelled':
                        interrupted[index] = record
                        run['interrupted_questions'] = [interrupted[i] for i in sorted(interrupted)]
                        run['interrupted_question'] = run['interrupted_questions'][0]
                    else:
                        completed[index] = record
                    run['results'] = [completed[i] for i in sorted(completed)]
                    run['summary'] = summarize_results(run['results'], total=len(items))
                    save()
        run['status'] = 'cancelled' if cancel_event.is_set() else ('done' if run['summary']['valid'] else 'invalid')
    except Exception as exc:
        requested = bool(run.get('cancel_requested'))
        run['status'] = 'cancelled' if requested else 'error'
        run['error'] = None if requested else str(exc)
        cancel_event.set()
        with _lock:
            for event in _eval_execution_events[tid].values():
                event.set()
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        a.use_temporal_handler, a.use_aggregation, a.ttl_schema_content, a.language, a.cancel_event = previous
        try:
            save()
        except Exception as exc:
            run.update(status='error', error=f'评测报告保存失败：{exc}')
        finally:
            with _lock:
                _eval_cancel_events.pop(tid, None)
                _eval_execution_events.pop(tid, None)
                _eval_agents.pop(tid, None)
                _eval_running = False


# --------------------------------------------------------------------------- #
# Exploration + SPARQL + Evaluation API
# --------------------------------------------------------------------------- #
@app.get("/api/prefixes")
def prefixes():
    g = _graph()
    ns = {p: str(u) for p, u in g.namespaces() if p}
    std = {
        "brick": "https://brickschema.org/schema/Brick#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
    }
    for k, v in std.items():
        ns.setdefault(k, v)
    block = "\n".join(f"PREFIX {p}: <{u}>" for p, u in ns.items())
    return {"namespaces": ns, "block": block}


@app.get("/api/classes")
def classes(limit: int = 80):
    if BrickGraph()._graph is None:
        raise HTTPException(status_code=400, detail="图谱未加载")
    return {"classes": _list_classes(max(1, min(limit, 200)))}


@app.get("/api/relations")
def relations(limit: int = 80):
    if BrickGraph()._graph is None:
        raise HTTPException(status_code=400, detail="图谱未加载")
    return {"relations": _list_relations(max(1, min(limit, 200)))}


@app.get("/api/class_instances")
def class_instances(t: str, limit: int = 60):
    if BrickGraph()._graph is None:
        raise HTTPException(status_code=400, detail="图谱未加载")
    g = _graph()
    types = {cls for cls in g.objects(None, RDF.type) if str(cls) == t or local_name(cls) == t}
    typeuri = next(iter(types)) if len(types) == 1 else None
    if typeuri is None:
        return {"type": t, "instances": []}
    out = []
    for u in sorted(set(g.subjects(RDF.type, typeuri)), key=str)[:max(1, min(limit, 200))]:
        labels = [str(o) for o in g.objects(u, RDFS.label)][:1]
        out.append({"id": short_name(u), "uri": str(u), "label": labels[0] if labels else None})
    return {"type": t, "instances": out}


@app.get("/api/relation_instances")
def relation_instances(pred: str, limit: int = 50):
    if BrickGraph()._graph is None:
        raise HTTPException(status_code=400, detail="图谱未加载")
    return {"pred": pred, "instances": _relation_instances(pred, limit)}


@app.get("/api/search")
def search(q: str, limit: int = 12):
    if BrickGraph()._graph is None:
        raise HTTPException(status_code=400, detail="图谱未加载")
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="空搜索词")
    return {"query": q, "results": _search_entities(q, limit),
            "implementation_mode": BrickGraph().implementation_mode,
            "diagnostic": getattr(BrickGraph(), 'last_tool_diagnostic', None)}


@app.get("/api/entity")
def entity(id: str = None, uri: str = None):
    if BrickGraph()._graph is None:
        raise HTTPException(status_code=400, detail="图谱未加载")
    ident = uri or id
    if not ident:
        raise HTTPException(status_code=400, detail="需提供 id 或 uri")
    return _entity_detail(ident)


@app.post("/api/sparql")
def sparql(req: SparqlRequest):
    if BrickGraph()._graph is None:
        raise HTTPException(status_code=400, detail="图谱未加载")
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="空查询")
    data, err = _safe_sparql(q, limit=req.limit)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return data


@app.get("/api/benchmarks")
def benchmarks():
    files = set()
    for d in (BASE_DIR, PROMPTS_DIR, BASE_DIR / 'benchmarks'):
        for p in sorted(d.glob("*.jsonl")):
            files.add(str(p.relative_to(BASE_DIR)).replace('\\', '/'))
    return {"benchmarks": sorted(files)}


@app.post("/api/evaluate")
def start_eval(req: EvalRequest):
    global _eval_running
    if BrickGraph()._graph is None:
        raise HTTPException(status_code=400, detail="图谱未加载")
    if _eval_running or _active_tid or _loading:
        raise HTTPException(status_code=409, detail="查询、加载或评测进行中，请稍候。")
    if agent is None:
        raise HTTPException(status_code=400, detail="Agent 未初始化")
    bench = req.benchmark
    path = bench if os.path.isabs(bench) else None
    if path is None and os.path.exists(str(BASE_DIR / bench)):
        path = str(BASE_DIR / bench)
    if path is None and os.path.exists(str(PROMPTS_DIR / bench)):
        path = str(PROMPTS_DIR / bench)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=400, detail=f"基准文件不存在: {bench}")
    try:
        items = _read_benchmark(path)
        _validate_benchmark_graph(items)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tid = "e" + uuid4().hex
    eval_tasks[tid] = {
        "status": "running",
        "summary": summarize_results([]),
        "results": [], "error": None,
    }
    with _lock:
        if _active_tid or _eval_running or _loading:
            eval_tasks.pop(tid, None)
            raise HTTPException(status_code=409, detail='另一项任务进行中')
        try:
            context_snapshot = _prepare_ttl_context(req)
        except Exception:
            eval_tasks.pop(tid, None)
            raise
        _eval_running = True
        _eval_cancel_events[tid] = threading.Event()
    threading.Thread(target=_run_eval, args=(tid, path, req.context, req.language, context_snapshot, req.workers), daemon=True).start()
    return {"task_id": tid}


@app.post('/api/eval_task/{tid}/cancel')
def cancel_evaluation(tid: str):
    with _lock:
        if tid not in eval_tasks:
            eval_task(tid)
        run = eval_tasks[tid]
        if run['status'] != 'running':
            return {'task_id': tid, 'status': run['status'], 'cancel_requested': False}
        event = _eval_cancel_events.get(tid)
        if event is None:
            raise HTTPException(status_code=409, detail='评测任务尚未就绪，请稍后重试')
        run.update(cancel_requested=True, cancel_requested_at=datetime.now().isoformat())
        event.set()
        execution_event = _eval_execution_events.get(tid)
        if execution_event is not None:
            for event in execution_event.values():
                event.set()
        return {'task_id': tid, 'status': 'running', 'cancel_requested': True}


@app.get("/api/eval_task/{tid}")
def eval_task(tid: str):
    if tid not in eval_tasks:
        if not re.fullmatch(r'e[0-9a-f]{32}', tid):
            raise HTTPException(status_code=404, detail="未知评测任务")
        saved = BASE_DIR / 'output' / 'evaluations' / tid / 'report.json'
        if not saved.is_file():
            raise HTTPException(status_code=404, detail="未知评测任务")
        try:
            restored = json.loads(saved.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=404, detail='评测报告无法读取') from exc
        restored.update(restored_from_disk=True, report_path=str(saved))
        if restored.get('status') == 'running':
            restored.update(status='interrupted', error='服务重启前评测未完成；已保存结果保留，未自动重跑。')
        eval_tasks[tid] = restored
    from copy import deepcopy
    with _lock:
        result = deepcopy(eval_tasks[tid])
        result['task_id'] = tid
        if result['status'] == 'running':
            currents = result.get('active_questions')
            if currents is None:
                currents = [result['current']] if result.get('current') else []
            for current in currents:
                current['elapsed_seconds'] = round(time.time() - current['started_at'], 1)
                runner = _eval_agents.get(tid, {}).get(current['index'] - 1)
                state = getattr(runner, '_current_state', None)
                if current.get('stage') == 'model' and state:
                    current.update(phase=state.phase, steps=len(state.actions), tokens=state.total_tokens)
            result['active_questions'] = currents
            result['current'] = currents[0] if currents else None
    return result


@app.get('/api/eval_task/{tid}/export')
def export_evaluation(tid: str):
    if tid not in eval_tasks:
        eval_task(tid)
    run = eval_tasks.get(tid)
    if not run or not run.get('report_path') or not Path(run['report_path']).is_file():
        raise HTTPException(status_code=404, detail='Evaluation report not available')
    return FileResponse(run['report_path'], media_type='application/json', filename=f'{tid}.json')


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("BRICK_PORT", "8000")), log_level="info")

