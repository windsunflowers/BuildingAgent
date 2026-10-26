import json,hashlib,copy
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from evaluation_metrics import summarize_results

def main():
 source=ROOT/'output/evaluations/e69c5d55371da4354b7c3f5f74f2ba16f/report.json'
 manifest=json.loads((ROOT/'output/validation/nine_gold_retry_task_20261026.json').read_bytes())
 retry=ROOT/'output/evaluations'/manifest['retry']['task_id']/'report.json'
 raw,raw_retry=source.read_bytes(),retry.read_bytes();old,new=json.loads(raw),json.loads(raw_retry)
 assert new['status'] in ('done','invalid'),new['status']
 assert len(new['results'])==9 and not new['summary']['gold_errors']
 items=[json.loads(line) for line in (ROOT/'output/validation/bldg11_mortar009_retry_20261026.jsonl').read_text(encoding='utf-8').splitlines()]
 rows=copy.deepcopy(old['results']);source_hash=hashlib.sha256(raw).hexdigest();retry_hash=hashlib.sha256(raw_retry).hexdigest()
 for r in rows:r['result_provenance']={'report_id':source.parent.name,'sha256':source_hash,'question_index':r['question_index']}
 for replacement in new['results']:
  item=items[replacement['question_index']-1];index=item['original_question_index'];previous=rows[index-1]
  assert previous['status']=='gold_error' and previous['question']==replacement['question']
  assert previous['gold_sparql']==replacement['gold_sparql']
  assert replacement['gold_count']==470 and replacement['gold_execution_status']=='success'
  row=copy.deepcopy(replacement);row['question_index']=index
  row['result_provenance']={'report_id':retry.parent.name,'sha256':retry_hash,'question_index':replacement['question_index'],'superseded_report_id':source.parent.name,'superseded_status':'gold_error'}
  rows[index-1]=row
 assert len(rows)==76 and all(r['status'] in ('done','error') for r in rows)
 tid='e'+uuid4().hex;target=ROOT/'output/evaluations'/tid/'report.json';target.parent.mkdir()
 provenance={'source_report_id':source.parent.name,'source_sha256':source_hash,'retry_report_id':retry.parent.name,'retry_sha256':retry_hash,'reused_questions':67,'replaced_questions':9,'mixed_execution_policy':True,'retry_configuration':new['configuration']}
 report=copy.deepcopy(old);report.update(task_id=tid,status='done',report_kind='supplemented_evaluation',created_at=datetime.now().isoformat(),results=rows,summary=summarize_results(rows,total=76),active_questions=[],current=None,error=None)
 report['configuration']['completion_provenance']=provenance
 report['configuration']['benchmark']=old['configuration']['benchmark']
 report['report_path']=str(target)
 target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 assert source.read_bytes()==raw and retry.read_bytes()==raw_retry
 result={'task_id':tid,'report':str(target),'summary':report['summary'],'provenance':{k:v for k,v in provenance.items() if k!='retry_configuration'}}
 (ROOT/'output/validation/bldg11_completed_report_20261026.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=True))
if __name__=='__main__':main()
