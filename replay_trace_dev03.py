"""Fully offline replay of locked v6.3 dev_03 plaintext model outputs.

No model/API calls. Replays frozen model-visible text through the actual
A/B/C scientific code and the deterministic evidence desk.
"""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parent
for d in ['code/synthetic_benchmark_v1/v6_one_shot','code/synthetic_benchmark_v1/preflight_rebuild']:
 sys.path.insert(0,str(ROOT/d))
from arms import run_a,run_b,run_c
from evidence_desk import OneShotEvidenceDesk

class FrozenModel:
 def __init__(self,arm,texts):self.arm=arm;self.texts=list(texts);self.calls=[]
 def call(self,*,system,user,tools,schema,arm,stage):
  if arm!=self.arm:raise AssertionError('cross-arm call')
  self.calls.append({'stage':stage,'schema':schema})
  if not self.texts:raise AssertionError('unexpected extra model call')
  return {'text':self.texts.pop(0),'tool_calls':[]}

def main():
 from importlib.util import spec_from_file_location,module_from_spec
 pub=ROOT/'data/synthetic_benchmark_v1/v6_synthetic_cases/public/development/dev_03'
 fixture=json.loads((ROOT/'demo_locked/dev_03/model_text_fixture.json').read_text())
 results={}
 for arm,func in [('A',run_a),('B',run_b),('C',run_c)]:
  model=FrozenModel(arm,fixture[arm]);marks=[]
  if arm=='A':r=func(model,lambda n,p:marks.append(n))
  else:
   desk=OneShotEvidenceDesk(pub)
   r=func(model,desk.disclose(),desk,lambda n,p:marks.append(n))
   assert desk.used,arm
  assert not model.texts,(arm,'unused text')
  results[arm]={'calls':len(model.calls),'stages':marks,'result_keys':list(r)}
 assert [results[x]['calls'] for x in ['A','B','C']]==[1,2,8]
 assert len([p for p in results['C']['stages'] if p.startswith('C_round_') and p.endswith('_challenge')])==3
 print(json.dumps({'status':'OFFLINE_REPLAY_PASS','arms':results},indent=2))
if __name__=='__main__':main()
