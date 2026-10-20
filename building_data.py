"""Recover only complete statements from bundled samples truncated at line limits."""
from pathlib import Path
from rdflib import Graph
from rdflib.plugins.parsers.notation3 import BadSyntax


def complete_turtle_prefix(text):
    quote = None
    iri = False
    comment = False
    depth = 0
    last = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if comment:
            comment = ch not in '\r\n'
        elif quote:
            if ch == '\\':
                i += 1
            elif text.startswith(quote, i):
                i += len(quote) - 1
                quote = None
        elif iri:
            if ch == '>':
                iri = False
        elif ch == '#':
            comment = True
        elif ch == '<':
            iri = True
        elif ch in '\"\'':
            quote = ch * 3 if text.startswith(ch * 3, i) else ch
            i += len(quote) - 1
        elif ch in '[(':
            depth += 1
        elif ch in '])':
            depth -= 1
        elif ch == '.' and depth == 0 and (i + 1 == len(text) or text[i+1].isspace() or text[i+1] == '#'):
            last = i + 1
        i += 1
    return text[:last]


def load_building_graph(path):
    path = Path(path).resolve()
    graph = Graph()
    try:
        graph.parse(path, format='turtle')
        return graph, []
    except BadSyntax as exc:
        bundled = Path(__file__).resolve().parent / 'prompts'
        if path.parent != bundled or 'sample' not in path.stem or 'EOF' not in str(exc):
            raise
        text = path.read_text(encoding='utf-8-sig')
        recovered = complete_turtle_prefix(text)
        if not recovered.strip() or recovered == text:
            raise
        # Parse from scratch: never retain half-built blank nodes from the failed parse.
        graph = Graph()
        graph.parse(data=recovered, format='turtle', publicID=path.as_uri())
        warning = f'附带样本末尾有不完整 Turtle 语句，已排除末尾 {len(text)-len(recovered)} 个字符；原文件保留。'
        return graph, [warning]
