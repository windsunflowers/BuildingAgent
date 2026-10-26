"""Explicit benchmark baselines; shared data/scoring does not share planners."""
from implementation_policy import policy_metadata

METHODS = ('brickqa', 'react')


def method_metadata(method, graph=None, baseline=None):
    if method not in METHODS:
        raise ValueError('Unknown evaluation method')
    if method == 'react':
        from react_reference import reference
        baseline = baseline or reference()
        return {'method':'react', 'baseline_reference':baseline, 'upstream_commit':baseline['commit'],
                'implementation_mode':baseline['implementation_mode'],
                'evaluation_graph':{'scope':baseline['execution_graph_scope'],
                                    'endpoint':baseline.get('endpoint'),
                                    'inference':baseline.get('graphdb_inference'),
                                    'ontology_merge':baseline['ontology_merge'],
                                    'triples':len(graph.source_graph) if graph is not None and baseline['execution_mode']=='local_rdflib' else None},
                'evaluation_policy':{'stop':'critic_FINAL_or_invalid_response_or_3_rounds',
                    'final_query':'last_generated_including_writer_or_critic_failure',
                    'sparql_timeout_seconds':180}}
    return {'method':'brickqa', 'method_policy':policy_metadata(graph)}


def evaluation_agent(source, method, backend='graphdb', building=None):
    if method == 'brickqa':
        return source
    if method == 'react':
        from react_baseline import ReActBaselineAgent
        return ReActBaselineAgent(source, backend=backend, building=building)
    raise ValueError('Unknown evaluation method')
