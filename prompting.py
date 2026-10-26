"""Language-specific prompts. English templates are byte-for-byte upstream copies."""
from pathlib import Path
import re
from brick_temporal_handler import should_use_temporal_guide

ROOT = Path(__file__).resolve().parent
MODEL_PROMPT_LANGUAGE = 'en'
LANGUAGE_POLICY = 'english-prompts-verbatim-history-ui-only-v2'


def save_prompt_snapshot(prompt):
    """Store exact model input once per hash for reproducible, concurrent runs."""
    import hashlib
    raw = prompt.encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    target = ROOT / 'logs/prompt_snapshots' / (digest + '.txt')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        from uuid import uuid4
        temporary = target.with_name(digest + '.' + uuid4().hex + '.tmp')
        temporary.write_bytes(raw)
        temporary.replace(target)
    return {'prompt_sha256': digest, 'prompt_file': str(target)}


def validate_language(language):
    if language not in ('zh', 'en'):
        raise ValueError('language must be zh or en')
    return language


def load_prompt(name, language='zh'):
    validate_language(language)
    directory = ROOT / 'prompts' / MODEL_PROMPT_LANGUAGE
    return (directory / name).read_text(encoding='utf-8')


def decomposition_policy(agent=None, *, use_decomposer=True, use_temporal_handler=True, use_aggregation=True):
    """Actual module configuration, shared by runtime and experiment records."""
    if agent is not None:
        use_decomposer, use_temporal_handler, use_aggregation = agent.use_decomposer, agent.use_temporal_handler, agent.use_aggregation
    enabled = bool(use_decomposer)
    temporal = bool(enabled and use_temporal_handler)
    operations = bool(enabled and use_aggregation)
    return {'version': 'module-ablation-v1', 'sensors': enabled,
            'temporal': temporal, 'operations': operations,
            'prompt_variant': ('disabled' if not enabled else
                               'full' if temporal and operations else
                               'sensors_only' if not temporal and not operations else 'partial'),
            'disabled_modules': 'excluded_from_prompt_and_result'}


def build_decomposition_prompt(question, language='zh', context='', *,
                               use_temporal=True, use_aggregation=True):
    """Derive module ablations without modifying the upstream template files."""
    validate_language(language)
    language = MODEL_PROMPT_LANGUAGE
    template = load_prompt('brick_decomposition.prompt', language)
    if not (use_temporal and use_aggregation):
        # Mixed temporal/operation examples are excluded from ablated prompts:
        # merely appending a disabling instruction would still expose them.
        prefix, output = template.split('# Output Format', 1)
        schema = output.split('```json', 1)[1].split('```', 1)[0]
        if not use_temporal:
            prefix = '\n'.join(line for line in prefix.splitlines()
                               if '**Temporal Constraints**' not in line and '**Extract Temporal**' not in line)
            schema = re.sub(r'  "temporal": \{.*?\n  \},\n', '', schema, flags=re.S)
        if not use_aggregation:
            prefix = '\n'.join(line for line in prefix.splitlines()
                               if '**Aggregations**' not in line and '**Extract Aggregations**' not in line)
            schema = re.sub(r'  "aggregation": \{.*?\n  \},\n', '', schema, flags=re.S)
        # Keep the original active instructions, domain mappings and schema.
        number = 0
        def renumber(match):
            nonlocal number
            number += 1
            return f'{number}. '
        prefix = re.sub(r'^\d+\.\s+', renumber, prefix, flags=re.M)
        if language == 'zh' and not use_aggregation:
            prefix = prefix.replace('sensor_id、type、operations', 'sensor_id')
        template = (prefix.rstrip() + '\n\n# Output Format\n'
                    'Return a JSON object with the following structure:\n\n```json'
                    + schema + '```\n\n' + '# Input' + template.rsplit('# Input', 1)[1])
    prompt = template.replace('{{ question }}', question)
    if context:
        prompt += '\nGraph context: ' + context
    return prompt


def build_controller_prompt(agent, state):
    en = True  # Interface language never changes model input.
    text = lambda zh, english: english if en else zh
    context = ''
    if agent.schema_description:
        title = text('建筑模式指南', 'BUILDING SCHEMA GUIDE')
        note = text('以下指南说明该建筑的结构、命名约定与查询模式。',
                    "The following guide explains the structure, naming conventions, and query patterns for this building.")
        context += f'\n{title}:\n------------------------------------\n{note}\n\n{agent.schema_description}\n------------------------------------\n\n'
    if agent.ttl_schema_content:
        sample = len(agent.ttl_schema_content) < 1000000
        title = text('BRICK 模式示例' if sample else '完整 BRICK 模式',
                     'BRICK SCHEMA SAMPLE' if sample else 'COMPLETE BRICK SCHEMA')
        note = text('这是该建筑模式的一个代表性样本。请使用 search_brick() 与 get_brick_entity() 动作来探索更多实体。' if sample else '这是该建筑的完整 Brick 模式。',
                    "This is a representative sample of the building's schema. Use search_brick() and get_brick_entity() actions to explore additional entities." if sample else 'This is the complete Brick schema for this building.')
        usage = text('用它来理解结构、实体、关系以及可用的传感器。',
                     'Use this to understand the structure, entities, relationships, and available sensors.')
        context += f'\n{title} (Turtle/TTL Format):\n------------------------------------\n{note}\n{usage}\n\n{agent.ttl_schema_content}\n------------------------------------\n\n'
    using_guide = bool(agent.use_temporal_handler and state.decomposition and state.decomposition.temporal.has_constraint
                       and should_use_temporal_guide(state.decomposition))
    if using_guide:
        context += '\n' + (ROOT / 'prompts/brick_temporal_patterns.txt').read_text(encoding='utf-8') + '\n'
    if state.decomposition:
        d = state.decomposition
        note = text('\n  请参考上面的时序模式指南来生成正确的时序 SPARQL。',
                    '\n  Follow the temporal patterns guide above to generate correct temporal SPARQL.') if agent.use_temporal_handler and d.temporal.has_constraint else ''
        sensors = ', '.join(s.sensor_id for s in d.sensors)
        aggregation = ', '.join(d.aggregation.operations) if agent.use_aggregation and d.aggregation.required else 'None'
        context += text(f'\n查询分解（用于指导你的动作）：\n- 所需传感器（共 {d.sensor_count} 个）：{sensors}',
                        f'\nQuery Decomposition (use this to guide your actions):\n- Sensors needed ({d.sensor_count}): {sensors}')
        if agent.use_temporal_handler:
            context += text(f'\n- 时间约束：{d.temporal.type}{note}', f'\n- Temporal constraint: {d.temporal.type}{note}')
        if agent.use_aggregation:
            context += text(f'\n- 聚合：{aggregation}', f'\n- Aggregation: {aggregation}')
        context += text(f'\n- 意图：{d.query_intent}\n\n', f'\n- Intent: {d.query_intent}\n\n')
    template = load_prompt('brick_controller.prompt', agent.language)
    # This runner has no conversation history. Render that optional block empty,
    # rather than sending unexpanded template markers to the model.
    template = re.sub(r'{% for i in range\(0, conversation_history\|length\) %}[\s\S]*?--\s*{% endfor %}', '', template)
    prompt = template.replace('{{ question }}', state.question)
    if context:
        prompt = prompt.replace('{% if action_history %}', context + '\n{% if action_history %}')
    history = '\n\n'.join(action.to_string(include_observation=True) for action in state.actions)
    replacements = {'{% if action_history %}': '', '{% for i in range(0, action_history|length) %}': '',
                    '{{ action_history[i] }}': history, '{% endfor %}': '', '{% endif %}': '',
                    '{% for i in range(0, conversation_history|length) %}': ''}
    for marker, value in replacements.items():
        prompt = prompt.replace(marker, value)
    return prompt, using_guide


def feedback(text, language):
    """Translate controlled tool messages, never questions, RDF values or SPARQL."""
    if language != 'en':
        return text
    messages = {
        '未找到结果。': 'No results found.', '未找到示例': 'No examples found',
        '实体不存在或名称不唯一，请提供完整 URI': 'Entity missing or ambiguous; provide the full URI',
        '缺少观测时间戳，无法验证时间约束': 'Missing observation timestamps; cannot validate the temporal constraint',
        '多个测点复用了同一个观测节点，应分别绑定观测节点并对齐时间戳': 'Multiple points reuse one observation node; bind distinct observations and align timestamps',
        '部分观测节点未绑定时间戳': 'Some observation nodes have no timestamp binding',
        '多传感器观测未对齐到同一时间戳': 'Multi-sensor observations are not aligned to the same timestamp',
        '当前请求': 'Current request', '时间约束': 'Temporal constraint', '缺少时间戳 FILTER': 'is missing a timestamp FILTER',
        '需要时间排序与 LIMIT，或按测点筛选最新时间戳': 'requires timestamp ordering and LIMIT, or per-point latest timestamps',
        '查询未包含请求的日期': 'Query does not contain the requested date',
        '校验警告（请修复后重新执行，不要直接结束）：': 'Validation warnings (repair and re-execute before stopping):',
        '执行错误：': 'Execution error: ', '查询未返回任何结果。状态：': 'No results. Status: ',
        '执行动作时出错：': 'Error executing action: ', '正在结束执行': 'Stopping execution',
        '按当前图谱的类型和实际关系生成查询': 'Build a query from the types and actual relationships in the loaded graph',
        '继续执行动作': 'Continue with the next action',
        '无法生成有效的输出格式': 'Unable to generate a valid output format',
        '检测到重复动作，正在停止': 'Duplicate action detected; stopping',
        '上一次输出的格式无效': 'The previous output had an invalid format',
        '最终查询尚未通过校验': 'The final query has not passed validation',
        '查询执行完成': 'Query execution completed', '完成': 'Done',
        '多测点观测没有在同一时间戳上关联，可能产生笛卡尔积': 'Observations are not joined on the same timestamp; this may create a Cartesian product',
        '无法验证多测点关联：': 'Cannot validate multi-point joins: ',
        '请根据最新执行错误或校验警告修正查询并重新执行，不能把探索片段或失败的查询作为答案。': 'Revise the query using the execution error or validation warnings, then execute it again. Do not use exploratory fragments or failed queries as final answers.',
        '最新查询有执行错误或校验警告': 'The latest query has execution errors or validation warnings',
        '查询已取消': 'Query cancelled',
        'Agent 因反复解析错误已停止': 'Agent stopped after repeated output parsing errors',
        'PREFIX 错误：': 'PREFIX error: ', 'SPARQL 执行错误：': 'SPARQL execution error: ',
        '请确保所有 PREFIX 声明都用尖括号正确书写。': 'Write every PREFIX URI inside angle brackets.',
        '所需前缀：brick:、bldg:、ref:、xsd:': 'Required prefixes: brick:, bldg:, ref:, xsd:',
        '未知动作：': 'Unknown action: ',
        '仅支持 SELECT 和 ASK 只读查询': 'Only read-only SELECT and ASK queries are supported',
        '本地图谱查询不支持远程 SERVICE': 'Remote SERVICE clauses are not supported for the local graph',
    }
    text = re.sub(r'查询超过 (\d+(?:\.\d+)?) 秒', r'Query exceeded \1 seconds', text)
    for source in sorted(messages, key=len, reverse=True):
        text = text.replace(source, messages[source])
    return text
