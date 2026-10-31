"""V6.2 deterministic evidence desk: a single immutable natural-language batch.

There is deliberately NO model-facing test menu. Each proposed investigation is
interpreted against only public data, independently; infeasible requests return
an explicit refusal rather than a vaguely related statistical result.
"""
from __future__ import annotations
import csv,hashlib,json,re
from pathlib import Path
import numpy as np

MAX_REQUESTS=2
MAX_REQUEST_CHARS=2400


def load_csv(path):
    with path.open('r',newline='',encoding='utf8') as f:
        rows=list(csv.DictReader(f))
    if not rows:raise ValueError('empty dataset')
    return {key:np.array([float(row[key]) for row in rows]) for key in rows[0]}


def contrast(y,x):
    a=y[x==1];b=y[x==0]
    if min(len(a),len(b))<10:raise ValueError('insufficient comparison groups')
    dif=float(np.mean(a)-np.mean(b));se=float(np.sqrt(a.var(ddof=1)/len(a)+b.var(ddof=1)/len(b)))
    return {'contrast':dif,'se':se,'ci95':[dif-1.96*se,dif+1.96*se],
            'n_treatment':len(a),'n_control':len(b)}


def adjusted(y,x,controls):
    X=np.column_stack((np.ones(len(y)),x,*controls));coef=np.linalg.lstsq(X,y,rcond=None)[0]
    residual=y-X@coef;gram=np.linalg.inv(X.T@X)
    hat=np.sum(X*(X@gram),axis=1)
    weighted=X*(residual/np.maximum(1e-7,1-hat))[:,None]
    cov=gram@(weighted.T@weighted)@gram
    se=float(np.sqrt(cov[1,1]));b=float(coef[1])
    return {'coefficient_X':b,'se_HC3':se,'ci95':[b-1.96*se,b+1.96*se],
            'interpretation':'Adjusted association; causal only under appropriate identification assumptions.'}


def _has(s,pattern):
    return re.search(pattern,s,re.I) is not None


def _normalize_text(text):
    return ' '.join(str(text).casefold().replace('_',' ').replace('–','-').split())


def _interpret(phrase):
    """Conservative intent resolution. Returns (kinds, refusal_reason).

    The requested intervention and target take precedence over incidental terms
    in the prose. No fuzzy fallback when a new design was explicitly proposed.
    A pair of separately specified mediator clamps counts as TWO tests.
    """
    s=_normalize_text(phrase)
    if not s.strip():return (), 'The request does not specify an analysis.'
    L=_has(s,r'\b(legitimacy|social acceptance|stigma|reputation|l score|l mediator|perceived l)\b')
    V=_has(s,r'\b(usefulness|practical value|utility|functional benefit|v score|v mediator|perceived v)\b')
    framing=_has(s,r'\b(framing|frames?|descriptions?|relational|attribute.bound|x assignment)\b')
    # Unsupported interventions, novel moderators, or new outcome constructs are
    # not silently substituted with an existing RCT/mediator manipulation.
    new_design=_has(s,r'\b(procurement|mandates?|accommodation (?:policy|obligation|mandate)|funded (?:responsibility|program|programme)|beneficiar(?:y|ies) (?:scope|coverage|count|number|range)|coverage|task[- ]information|application[- ]information|readability|comprehension|audience accountability|implementation burden|reporting pressure|real purchases|field deployment)\b')
    new_intervention=_has(s,r'\b(cross(?:ing|ed)?|factorial|independently randomiz\w*|independently randomis\w*|manipulat\w*|experimentally var\w*|interven\w*|hold\w* constant|fix\w*|neutraliz\w*|neutralis\w*|suppress\w*|block\w*|remove\w*|turn off|experimentally prevent\w*|vary\w*|randomiz\w*|randomis\w*)\b')
    known_target=(L or V)
    if new_design and (new_intervention or _has(s,r'\b(under|across|versus|moderation|interact\w*)\b')):
        return (), 'Requested intervention or moderator is not represented by an available randomized dataset; no substitute has been supplied.'
    if new_design and _has(s,r'\b(measure|collect|test whether|examine|compare|estimate)\b') and not (L or V):
        return (), 'Requested construct or design is not measured in the public study; no substitute has been supplied.'
    # Interpret explicit empirical requests before later conjectures about mediators.
    # Before/after adjustment is one coherent baseline comparison; fit-specific
    # differences, when also requested, are a separate analysis. Nothing here
    # infers a causal effect from observational differences.
    baseline=_has(s,r'\b(baseline|observational|observed|non.randomized|non.randomised|records|sample|evaluations|dataset)\b')
    adjust=_has(s,r'\b(adjust\w*|control for|conditional|confound\w*|selection|account for|partial out)\b')
    raw_and_adjusted=_has(s,r'\b(before and after|unadjusted and adjusted|raw and adjusted|with and without controls|both unadjusted and adjusted)\b')
    fit_subgroup=_has(s,r'\b(heterogene\w*|subgroups?|stratif\w*|moderators?|moderation|effect modification|interaction|high[- ]fit|low[- ]fit|vary by technical fit|varies by technical fit|vary with technical fit|varies with technical fit)\b') and _has(s,r'\b(fit|compatibility|f index)\b')
    if baseline and adjust and raw_and_adjusted and not new_intervention:
        return (('baseline_compare_adjusted','fit_heterogeneity') if fit_subgroup else ('baseline_compare_adjusted',)),None
    if baseline and adjust and fit_subgroup and not new_intervention:
        return ('baseline_adjusted','fit_heterogeneity'),None
    clamp=_has(s,r'\b(neutraliz\w*|neutralis\w*|clamp\w*|block\w*|suppress\w*|fix\w*|hold\w*|disable\w*|eliminat\w*|prevent\w*|remove\w*|turn off|set to zero)\b')
    encourage=_has(s,r'\b(encourag\w*|nudg\w*|boost\w*|experimentally increas\w*|randomiz\w* mediator|randomis\w* mediator)\b')
    # If mediator is merely MENTIONED as a measured secondary outcome, do not
    # infer a mediation or blocking experiment.
    if clamp and (L or V):
        return tuple(k for flag,k in ((L,'neutralize_l'),(V,'neutralize_v')) if flag),None
    if encourage and (L or V) and _has(s,r'\b(mediator|mediat\w*|score|legitimacy|usefulness)\b') and not _has(s,r'\b(description|frame|framing) effects? on\b'):
        return tuple(k for flag,k in ((L,'encourage_l'),(V,'encourage_v')) if flag),None
    if _has(s,r'\b(which|whether|distinguish|compare)\b') and L and V and _has(s,r'\b(mediators?|mediat\w*|pathways?|causal mechanisms?)\b'):
        # A request to know *which* pathway dominates is not itself a named
        # experiment. It is fulfilled only when it proposes a specific design.
        return (), 'A mediator comparison requires a specified intervention or analysis; no experiment was implied automatically.'
    heterogeneity=_has(s,r'\b(heterogene\w*|subgroups?|stratif\w*|moderators?|moderation|effect modification|interaction|high[- ]fit|low[- ]fit|vary by technical fit|varies by technical fit|vary with technical fit|varies with technical fit|separately)\b')
    if heterogeneity and _has(s,r'\b(fit|compatibility|f index)\b'):
        return ('fit_heterogeneity',),None
    if heterogeneity:
        return (), 'The requested moderator is not supported by a matched randomized comparison.'
    randomize_frame=_has(s,r'\b(randomiz\w*|randomis\w*|randomized|randomised|randomly assigned|rct|trial|experiment|causal effect|intention.to.treat)\b') and framing
    if randomize_frame:
        return ('frame_trial',),None
    if _has(s,r'\b(adjust\w*|control for|conditional|confound\w*|selection|account for|partial out)\b'):
        return ('baseline_adjusted',),None
    if framing and _has(s,r'\b(contrast|compar\w*|difference|association|correlat\w*|regress\w*|estimate|effect|mean)\b'):
        return ('baseline_contrast',),None
    return (), 'No specific feasible statistical estimand or experiment was identified; no unrelated test substituted.'


def _requested_test(phrase):
    """Compatibility helper; never used to substitute unrelated tests."""
    kinds,reason=_interpret(phrase)
    if len(kinds)==2 and set(kinds)=={'neutralize_l','neutralize_v'}:return 'neutralize_both'
    if len(kinds)==2 and set(kinds)=={'encourage_l','encourage_v'}:return 'encourage_both'
    return kinds[0] if kinds else 'uninterpretable'


class OneShotEvidenceDesk:
    def __init__(self,public_case):
        path=Path(public_case).resolve()
        if any(piece.lower()=='private' for piece in path.parts):raise ValueError('private path denied')
        card=json.loads((path/'card.json').read_text(encoding='utf8'))
        if set(card)!={'case_id','synthetic_population','observations','variables','study_design','evidence_access'}:
            raise ValueError('unexpected public card fields')
        self.path=path;self.card=card;self.used=False;self.locked_request=None;self.receipts=[]

    def disclose(self):
        """Disclose research DESIGN and columns only, never statistics or truth.

        A dataset inventory is not a test catalogue: it says what material is
        available, but does not recommend any analysis or reveal a result.
        """
        study=json.loads(json.dumps(self.card))
        definitions={
          'baseline.csv':('Baseline evaluation','Observational X unless the public study card states X was randomized'),
          'trial.csv':('Separate follow-up evaluation','Description X was randomized'),
          'neutralize_l.csv':('Separate intervention evaluation','Description X randomized; the perceived legitimacy score L was experimentally fixed at zero'),
          'neutralize_v.csv':('Separate intervention evaluation','Description X randomized; the perceived usefulness score V was experimentally fixed at zero'),
          'encouragement.csv':('Separate randomized encouragement evaluation','Independent encouragement assignments ZL and ZV for legitimacy and usefulness scores; exclusion assumptions not established')
        }
        inventory=[]
        for filename,(label,design) in definitions.items():
            source=self.path/filename
            if not source.is_file():continue
            with source.open('r',newline='',encoding='utf8') as handle:
                reader=csv.reader(handle)
                cols=next(reader)
                n=sum(1 for _ in reader)
            if filename=='baseline.csv':design=self.card['study_design']
            inventory.append({'description':label,'study_design':design,
                              'variables':cols,'observations':n})
        study['existing_data'] = inventory
        study['evidence_scope'] = ('The evidence desk can analyze only the existing datasets described above. '
            'It cannot collect new data or create new intervention conditions. '
            'In your one irreversible request, describe up to two specific analyses in ordinary words. '
            'The inventory lists study resources, not recommended analyses or their results. '
            'Future unperformed experiments may be proposed in your scientific discussion, '
            'but cannot be executed by this evidence desk.')
        return study

    def request(self,requests):
        if self.used:raise ValueError('one_evidence_request_already_consumed')
        self.used=True
        self.locked_request={'verbatim':requests,'status':'submitted'}
        if not isinstance(requests,list) or not requests:
            self.locked_request['status']='invalid_or_over_budget'
            return [{'status':'invalid_or_over_budget','message':'No evidence request submitted; opportunity consumed.'}]
        if len(requests)>MAX_REQUESTS:
            self.locked_request['status']='invalid_or_over_budget'
            return [{'status':'invalid_or_over_budget','message':'More than two separately requested investigations; opportunity consumed.'}]
        seen=set()
        for phrase in requests:
            if not isinstance(phrase,str) or len(phrase.strip())<8 or len(phrase)>MAX_REQUEST_CHARS:
                self.receipts.append({'status':'invalid_request','requested':str(phrase)[:500],
                    'reason':'Unusable or excessively long individual request. Other requests were evaluated independently.'})
                continue
            choices,reason=_interpret(phrase)
            if reason:
                self.receipts.append({'status':'infeasible','requested':phrase,'reason':reason,'no_substitution':True})
                continue
            if len(seen|set(choices))>MAX_REQUESTS:
                self.receipts.append({'status':'over_budget','requested':phrase,
                    'reason':'This request would exceed the two-distinct-analysis cap; no partial substitution.'})
                continue
            for kind in choices:
                if kind in seen:continue
                seen.add(kind)
                self.receipts.append(self._execute(kind,phrase))
        self.locked_request['resolved']=sorted(seen)
        return json.loads(json.dumps(self.receipts))

    def _execute(self,kind,phrase):
        base=self.path/'baseline.csv'
        extra={'frame_trial':'trial.csv','neutralize_l':'neutralize_l.csv','neutralize_v':'neutralize_v.csv',
               'encourage_l':'encouragement.csv','encourage_v':'encouragement.csv'}
        path=self.path/extra.get(kind,'baseline.csv')
        if kind=='frame_trial' and self.card['study_design'].startswith('description randomized'):
            path=base
        if not path.is_file():
            return {'status':'infeasible','requested':phrase,
                'reason':'The specifically requested evidence is not available in this study. No alternative was substituted.',
                'resolved_test':kind,'no_substitution':True}
        data=load_csv(path)
        if kind=='baseline_contrast':
            result={'baseline_X_to_Y':contrast(data['Y'],data['X']),
                    'design':self.card['study_design'],
                    'limitations':'Raw difference, not necessarily a causal effect.'}
        elif kind=='baseline_adjusted':
            result={'adjusting_Q_F':adjusted(data['Y'],data['X'],[data['Q'],data['F']]),
                    'design':self.card['study_design'],
                    'limitations':'Not causal without sufficient covariate exchangeability and overlap.'}
        elif kind=='baseline_compare_adjusted':
            result={'unadjusted_X_to_Y':contrast(data['Y'],data['X']),
                    'adjusting_Q_F':adjusted(data['Y'],data['X'],[data['Q'],data['F']]),
                    'design':self.card['study_design'],
                    'limitations':'Before/after adjustment describes associations; attenuation does not prove selection or mediation.'}
        elif kind=='frame_trial':
            result={'randomized_framing_total_effect':contrast(data['Y'],data['X']),
                    'secondary_score_contrasts':{n:contrast(data[n],data['X']) for n in ('L','V','Q','F') if n in data},
                    'observed_missingness':{n:int(np.isnan(v).sum()) for n,v in data.items()},
                    'design':'X independently randomized as documented; timing of individual scores beyond study card not independently established',
                    'limitations':'Secondary score contrasts are effects on scores, not identified mediator effects; post-treatment adjustment is not performed.'}
        elif kind=='fit_heterogeneity':
            hi=data['F']>=0
            randomized = self.card['study_design'].startswith('description randomized')
            prefix='X_effect' if randomized else 'X_association'
            result={prefix+'_F_below_zero':contrast(data['Y'][~hi],data['X'][~hi]),
                    prefix+'_F_above_or_equal_zero':contrast(data['Y'][hi],data['X'][hi]),
                    'design':self.card['study_design'],
                    'limitations':('Randomized X subgroup contrasts conditional on F measured before assignment; '
                        'uncertainty across subgroups does not establish a moderator without an interaction test.'
                        if randomized else
                        'Descriptive subgroup associations ONLY; X was not randomized, so no causal effect heterogeneity is identified.')}
        elif kind in ('neutralize_l','neutralize_v'):
            result={'randomized_X_effect_with_'+('L' if kind=='neutralize_l' else 'V')+'_fixed':contrast(data['Y'],data['X']),
                    'design':'Fresh randomized X with targeted score fixed to zero under generating intervention; no claim of natural mediation identification.'}
        elif kind in ('encourage_l','encourage_v'):
            t=kind[-1].upper()
            result={'interventions':{t:{'Z_effect_on_'+t:contrast(data[t],data['Z'+t]),
                                      'Z_effect_on_Y':contrast(data['Y'],data['Z'+t])}},
                    'design':'Randomized designated-score encouragement, subject to exclusion assumptions.'}
        else:raise AssertionError('unsupported mapping')
        return {'status':'ok','requested':phrase,'resolved_test':kind,'case_id':self.card['case_id'],
                'dataset_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'receipt_id':'TEST:'+self.card['case_id']+':'+kind,'result':result}
