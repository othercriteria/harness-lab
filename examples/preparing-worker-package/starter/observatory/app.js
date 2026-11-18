'use strict';
const $=id=>document.getElementById(id);
const state={run:null,trial:null,runs:[],paused:false,busy:false,signature:'',view:'timeline',page:1,pageSize:20,query:'',pagination:null,listSignature:'',revision:0,pending:false,artifactScope:'',artifactRevision:0,eventStart:null,eventWindow:null,eventScope:'',eventOpen:new Map(),eventNested:new Map()};
function node(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function json(value){return JSON.stringify(value,null,2);}
function secs(n){return typeof n==='number'?`${n.toFixed(1)}s`:'—';}
function statusClass(s){return ['passed','complete'].includes(s)?'good':['failed','runtime nonconformance','correct code / handoff failed','supported blocker / handoff failed','unsupported blocker','stopped with error','read failed','transport stopped','attempt ended / tool receipt unavailable','attempt deadline reached','request timed out','attempt ended / response unavailable'].includes(s)?'bad':['live','in progress','executing','reading','adapter pending','awaiting response'].includes(s)?'live':'';}
function badge(s){return node('span',s,`badge ${statusClass(s)}`);}
async function api(path,args={}){const r=await fetch(`/api/${path}?${new URLSearchParams(args)}`,{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);return d;}
function requestRefresh(){state.revision++;refresh(true);}
function select(run,trial=null){state.run=run;state.trial=trial;state.signature='';resetEvents();resetArtifact();$('follow').checked=false;runList();requestRefresh();}
function changePage(page){if(!state.pagination)return;state.page=Math.max(1,Math.min(page,state.pagination.pages));$('follow').checked=false;requestRefresh();}
function resetEvents(){state.eventStart=null;state.eventWindow=null;state.eventScope='';state.eventOpen.clear();state.eventNested.clear();}
function changeEventPage(direction){
  const page=state.eventWindow;if(!page)return;
  const start=direction==='older'?page.older_start:direction==='newer'?page.newer_start:null;
  if(direction!=='latest'&&start==null)return;
  state.eventStart=start;$('follow').checked=false;requestRefresh();
}
function eventNavigation(trace){
  const page=trace?.event_window;state.eventWindow=page??null;
  $('older-events').disabled=page?.older_start==null;
  $('newer-events').disabled=page?.newer_start==null;
  $('latest-events').disabled=!page||page.latest;
  $('event-page-info').textContent=page?`Events ${(page.total_events??page.total_requests)?page.start+1:0}–${page.end} of ${page.total_events??page.total_requests} · ${page.latest?'Latest (updates as events arrive)':'History (position held)'} · up to ${page.limit} per view`:'';
}
function runOutcomeSummary(run){
  const trials=run.trials;
  if(run.kind==='delegated')return `Delegated work · ${trials.at(-1)?.state||'preparing'}`;
  if(run.kind==='diagnostic')return `${trials.filter(t=>t.state==='diagnostic reviewed').length}/${trials.length} diagnostics reviewed`;
  if(trials.some(t=>t.comparison_review)){
    const accepted=trials.filter(t=>t.passed===true).length;
    const invalid=trials.filter(t=>t.comparison_review?.status==='operationally_invalid').length;
    const pending=trials.filter(t=>t.comparison_review?.status==='pending_outer_review').length;
    return `${accepted}/${trials.length-invalid} accepted${invalid?` · ${invalid} operationally invalid`:''}${pending?` · ${pending} awaiting review`:''}`;
  }
  if(run.kind==='control'||!trials.some(t=>t.adjudication))return `${trials.filter(t=>t.state==='passed').length}/${trials.length} ${run.kind==='control'?'controls':'trials'} passed`;
  const counts={coding:0,blocker:0,pending:0,failed:0,rejected:0,stopped:0,live:0,unfinished:0};
  for(const t of trials){
    if(t.state==='passed')counts.coding++;
    else if(t.state==='supported blocker')counts.blocker++;
    else if(t.state==='runtime nonconformance')counts.rejected++;
    else if(t.state==='failed'||t.state==='unsupported blocker'||t.state==='supported blocker / handoff failed'||t.state==='correct code / handoff failed')counts.failed++;
    else if(/unsafe cleanup|cancelled|stopped/.test(t.state))counts.stopped++;
    else if(t.adjudication?.status==='pending_outer_rubric')counts.pending++;
    else if(t.state==='in progress')counts.live++;
    else counts.unfinished++;
  }
  return [
    [counts.coding,'coding pass','coding passes'],[counts.blocker,'supported blocker','supported blockers'],
    [counts.rejected,'nonconforming run','nonconforming runs'],
    [counts.pending,'awaiting review','awaiting review'],[counts.failed,'failed trial','failed trials'],
    [counts.stopped,'stopped trial','stopped trials'],[counts.live,'in progress','in progress'],
    [counts.unfinished,'unfinished','unfinished']
  ].filter(([n])=>n).map(([n,one,many])=>`${n} ${n===1?one:many}`).join(' · ');
}
function diagnosticMetrics(current,adjudication){
  const result=adjudication?.diagnostic_results;
  if(current?.diagnostic_kind==='input-probe')return [
    ['Diagnostic review',adjudication?.status==='adjudicated'?'REVIEWED':'PENDING'],
    ['Probe format',result?result.format_valid?'VALID':'INVALID':'PENDING'],
    ['Inputs within contract',result?result.inputs_valid?'YES':'NO':'PENDING'],
    ['Deterministic replay',result?result.deterministic?'YES':'NO':'PENDING'],
    ['Behavioral difference',result?result.format_valid&&result.inputs_valid&&result.deterministic?result.difference_found?'FOUND':'NOT FOUND':'UNQUALIFIED':'PENDING'],
    ['Clean completion',current?.clean===true?'YES':current?.clean===false?'NO':'PENDING'],
    ['Probe-author time',secs(current?.seconds)],['Coding-goal credit','NONE']];
  return [['Diagnostic review',adjudication?.status==='adjudicated'?'REVIEWED':'PENDING'],
    ['Soundness controls',result?result.sound_on_controls?'PASS':'FAIL':'PENDING'],
    ['Defect detection',result?result.sound_on_controls?`${result.incorrect_controls_detected}/${result.incorrect_controls_total}`:'UNSOUND TESTS':'PENDING'],
    ['Clean completion',current?.clean===true?'YES':current?.clean===false?'NO':'PENDING'],
    ['Author time',secs(current?.seconds)],['Coding-goal credit','NONE']];
}
function runList(){
  const p=state.pagination;if(!p)return;
  $('run-count').textContent=p.query?`${p.matching} / ${p.total}`:String(p.total);
  const start=p.matching?(p.page-1)*p.page_size+1:0;
  $('page-info').textContent=`${start}–${Math.min(p.page*p.page_size,p.matching)} of ${p.matching} · Page ${p.page}/${p.pages}`;
  $('previous-page').disabled=p.page<=1;$('next-page').disabled=p.page>=p.pages;
  const outside=state.run&&!state.runs.some(r=>r.name===state.run);
  $('selected-campaign').hidden=!outside;
  $('selected-campaign').textContent=outside?`Viewing ${state.run} (outside this page)`:'';
  $('page-warning').hidden=!p.unavailable?.length;
  $('page-warning').textContent=p.unavailable?.length?`${p.unavailable.length} campaign(s) temporarily unavailable; retrying on refresh.`:'';
  const signature=json([state.runs,state.run,p.query]);if(signature===state.listSignature)return;
  state.listSignature=signature;
  const frag=document.createDocumentFragment();
  for(const r of state.runs){const b=node('button',undefined,`run ${r.name===state.run?'selected':''}`);b.append(node('span',r.name,'run-name'),node('span',`${r.state} · ${runOutcomeSummary(r)}`,'run-meta'));b.onclick=()=>select(r.name);frag.append(b);}
  if(!p.matching)frag.append(node('p',p.query?'No matching campaigns.':'No campaigns yet.','hint'));
  $('runs').replaceChildren(frag);
}
function block(parent,title,value){if(value===undefined||value===null||value==='')return;parent.append(node('h3',title),node('pre',typeof value==='string'?value:json(value)));}
function rawDetails(parent,title,value){const d=node('details');d.append(node('summary',title),node('pre',typeof value==='string'?value:json(value)));parent.append(d);}
function editText(parent,args){
  block(parent,'Path',args.path);
  for(const [key,title] of [['old_text','Old text'],['new_text','New text']]){
    if(typeof args[key]==='string'){
      parent.append(node('h3',title),node('pre',args[key]));
      if(args[key]==='')parent.append(node('span','Empty string','meta'));
    }
  }
}
function writeText(parent,args){
  block(parent,'Path',args.path);
  if(typeof args.content==='string'){
    parent.append(node('h3','Content'),node('pre',args.content));
    if(args.content==='')parent.append(node('span','Empty string','meta'));
  }
}
function requestedTools(parent,calls){
  if(!calls?.length)return;
  block(parent,'Requested tools','Decoded for inspection; this does not establish acceptance or execution.');
  for(const call of calls){
    const f=call?.function;
    if(!f)continue;
    block(parent,'Tool',f.name);
    let args=f.arguments;
    try{if(typeof args==='string')args=JSON.parse(args);}catch{block(parent,'Arguments','Not valid JSON; inspect raw payload below.');continue;}
    if(!args||typeof args!=='object'||Array.isArray(args))continue;
    if(f.name==='bash'&&typeof args.command==='string')block(parent,'Command',args.command);
    else if(f.name==='edit_file')editText(parent,args);
    else if(f.name==='write_file')writeText(parent,args);
    else block(parent,'Decoded arguments',args);
  }
  rawDetails(parent,'Raw requested tools (API representation)',calls);
}
function handoffEvidence(envelope) {
  const panel = $('handoff-evidence');
  const handoff = envelope?.handoff;
  panel.replaceChildren();
  panel.hidden = !handoff;
  if (!handoff) return;
  panel.append(node('h2', 'Worker handoff and cited evidence'));
  block(panel, 'Worker summary', handoff.summary);
  const receipt = envelope.execution_receipt;
  const observations = receipt?.selected_observations?.observations ?? [];
  for (const item of handoff.evidence ?? []) {
    if (item.kind === 'public_contract') {
      block(panel, 'Public contract clause cited by Worker', item.public_clause);
      block(panel, 'Worker interpretation', item.supports);
      continue;
    }
    const row = observations.find(record => record.observation_id === item.observation_id);
    panel.append(node('h3', 'Worker citation · ' + item.observation_id));
    if (item.supports) panel.append(node('p', item.supports));
    if (!row) {
      panel.append(node('p', 'Recorded operation unavailable in this summary.'));
      continue;
    }
    block(panel, row.command_clipped ? 'Recorded command (clipped)' : 'Recorded command', row.command);
    const flags = [];
    if (row.originally_truncated) flags.push('original tool output truncated');
    if (row.excerpt_clipped) flags.push('excerpt clipped for display');
    const status = row.returncode == null ? 'exit status unavailable' : 'exit ' + row.returncode;
    block(panel, ['Recorded response', status, ...flags].join(' · '), row.original_visible_excerpt || '(no excerpt recorded)');
  }
  if (handoff.unverified?.length) block(panel, 'Worker limitations', handoff.unverified.join('\n'));
  const files = receipt?.current_public_state;
  if (files?.file_comparison === 'captured') {
    block(panel, 'Harness file comparison since task start', {
      changed_files: files.changed_files, omitted: files.changed_files_omitted
    });
  } else if (files) {
    panel.append(node('p', 'File comparison since task start unavailable.'));
  }
  panel.append(node('p', 'Inspect final-handoff.json in Raw artifacts for the original cited observations. Compare verification claims in the submitted files as well.', 'hint'));
}

function progressReport(parent,report,measurement){
  if(report==null)return;
  const panel=node('section');
  panel.append(node('h4','Progress report · model claims'));
  panel.append(node('p','Reported progress is unverified. Citations are historical; passing check claims and empty remaining work do not establish correctness.'));
  if(typeof report!=='object'||Array.isArray(report)){block(panel,'Malformed report',report);parent.append(panel);return;}
  block(panel,'Change since prior report or task start',report.change??'unknown');
  block(panel,'Implemented · claimed',report.implemented);
  block(panel,'Check outcomes · claimed',report.checks);
  block(panel,'Remaining or unverified requirements',report.remaining);
  block(panel,'Obstacle',report.obstacle===''?'None reported':report.obstacle);
  block(panel,'Next action',report.next_action);
  block(panel,'Historical citations',report.evidence);
  block(panel,'Reporting cost',measurement??{note:'See checkpoint request time and tokens. Marginal report overhead is not separately observed.'});
  parent.append(panel);
}
function eventCard(e,open){const d=node('details',undefined,`event ${e.kind}`);d.dataset.event=e.id;d.open=open;const title=node('summary');const kind=e.kind==='context'?(e.phase==='reset'?'RESET':e.phase==='scope'?'SCOPE':e.phase==='continuation'?'CONTINUATION':'CHECKPOINT'):e.kind==='model'?'MODEL':e.tool_name==='checkpoint_context'?'CHECKPOINT':e.tool_name==='return_scope'?'RETURN':e.review_control?'REVIEW':e.adapter_control?'FINALIZE':e.tool_name==='edit_file'?'EDIT':e.tool_name==='write_file'?'WRITE':e.tool_name==='read_file'?'READ':e.tool_name==='run_checks'?'CHECK':!e.tool_name||['bash','execute'].includes(e.tool_name)?'BASH':'TOOL';let desc;if(e.kind==='context'){desc=e.reason||e.state;}else if(e.kind==='model'){desc=`${e.finish||e.state} · ${e.usage?.completion_tokens??(e.request_end?'unknown':'…')} output tokens · ${secs(e.seconds)}`;}else{desc=e.adapter_control?`${e.tool_name} · ${e.tool_name==='checkpoint_context'?(e.checkpoint_control?'unverified memory saved':e.state):e.tool_name==='return_scope'?'return recorded; not submitted':e.review_control?'review requested; not submitted':e.terminal_control||'pending'} · no command execution`:['edit_file','write_file','read_file'].includes(e.tool_name)?`${e.tool_name} · ${e.arguments?.path||'pending'}${e.tool_name==='read_file'?` · from line ${e.arguments?.start_line??1}, up to ${e.arguments?.max_lines??200} lines`:''}`:(e.command||'').split('\n')[0].slice(0,120)||e.state;}title.append(node('span',e.id,'sequence'),node('span',kind,'event-kind'),node('span',desc,'event-title'),badge(e.state));d.append(title);const body=node('div',undefined,'event-body');if(e.kind==='context'){block(body,'Context recovery',e.lifecycle);block(body,'Receipt',e.artifact);}else if(e.kind==='model'){block(body,'Request', {seed:e.seed,max_tokens:e.limit,messages:e.messages,finish_reason:e.finish,usage:e.usage});block(body,'Request ended',e.request_end);block(body,'Parser-control evidence',e.control_case);block(body,'Context policy',e.context);block(body,'Context accounting',e.context_usage);if(e.initial_prompt){const prompt=node('details');prompt.append(node('summary','Initial system & task prompts'),node('pre',json(e.initial_prompt)));body.append(prompt);}if(e.reasoning){const reasoning=node('details');reasoning.append(node('summary','Reasoning emitted by model'),node('pre',e.reasoning));body.append(reasoning);}block(body,'Assistant content',e.content);requestedTools(body,e.tool_calls);}else if(e.adapter_control){block(body,'Tool',e.tool_name);if(e.tool_name==='checkpoint_context')progressReport(body,e.arguments?.progress,e.progress_measurement);block(body,e.tool_name==='checkpoint_context'?'Checkpoint (unverified memory)':'Model handoff (unverified)',e.arguments);block(body,'Adapter status',{terminal:(e.review_control||['checkpoint_context','return_scope'].includes(e.tool_name))?'not submitted':e.terminal_control??'pending',review:e.review_control??null,checkpoint:e.checkpoint_control??null,scope:e.scope_control??null,request_accepted:e.result?.ok??null,executed:e.executed,cleanup_required:e.cleanup_required,notice:e.executed===false?'No shell command executed. No new sandbox cleanup receipt is required.':'Execution status not established.'});block(body,'Adapter message',e.result?.stdout);block(body,'Adapter error',e.result?.stderr);if(e.cleanup)block(body,'Unexpected cleanup artifact (inspect raw evidence)',e.cleanup);}else if(e.tool_name==='read_file'){
  const result=e.result,visible=result?.visible;
  block(body,'Tool','read_file');
  block(body,'Read request',e.arguments);
  block(body,'Read status',result?{ok:result.ok,seconds:result.wall_seconds,returncode:visible?.returncode,truncated:visible?.truncated,exception_info:visible?.exception_info,executed:result.executed,read_only:result.read_only,cleanup_required:result.cleanup_required,notice:result.executed===false&&result.read_only===true?'Read-only workspace snapshot inspection; no shell process or new sandbox cleanup required.':'Inspect raw receipt for execution status.'}:{state:e.state});
  block(body,'File identity and range',visible?.file_read);
  block(body,visible?.file_read?.contents_returned===false?'Existing context reference':'Returned text',visible?.output);
  if(e.cleanup)block(body,'Unexpected cleanup artifact (inspect raw evidence)',e.cleanup);
}else{if(e.tool_name==='edit_file'){block(body,'Tool','edit_file');editText(body,e.arguments||{});rawDetails(body,'Exact edit arguments (API representation)',e.arguments);}else if(e.tool_name==='write_file'){block(body,'Tool','write_file');writeText(body,e.arguments||{});rawDetails(body,'File write arguments (API representation)',e.arguments);}else{block(body,'Tool',e.tool_name);block(body,'Command',e.command);if(!e.command)block(body,'Arguments',e.arguments);}const result=e.result;block(body,'Tool status',result?{returncode:result.returncode,stopped_by:result.stopped_by,seconds:result.wall_seconds,ok:result.ok}:{state:e.state,timeout:e.timeout});block(body,'stdout',result?.stdout||e.transport_stdout);block(body,'stderr',result?.stderr||e.transport_stderr);block(body,'Check record (historical; not a correctness verdict)',e.check_record);block(body,'Workspace snapshot',result?.snapshot);if(result?.scratch_snapshot){block(body,'Attempt scratch snapshot',result.scratch_snapshot);block(body,'Scratch scope','Files preserved between tools in this attempt; excluded from the submitted workspace and evaluator. This receipt does not establish task correctness.');}block(body,'Cleanup',e.cleanup?{verified:e.cleanup.verified,active_state:e.cleanup.active_state}:null);}d.append(body);return d;}
function costBreakdown(value){
  $('cost-breakdown').hidden=!value;
  if(!value)return;
  $('cost-state').textContent=value.status;
  const fields=[
    ['Task time',secs(value.task_seconds)],
    ['First structured edit attempt ≈',secs(value.first_structured_edit_seconds_approx)],
    ['After last structured edit attempt ≈',secs(value.after_last_structured_edit_seconds_approx)],
    ['Recorded model request time',secs(value.model_request_seconds)],
    ['Recovery requests · within model time',secs(value.checkpoint_request_seconds)],
    ['Finalization requests · within model time',secs(value.finalization_request_seconds)],
    ['Backend prefill · overlaps model time',secs(value.backend_prompt_seconds)],
    ['Backend generation · overlaps model time',secs(value.backend_predicted_seconds)],
    ['Automatic evaluator',secs(value.verification_seconds)],
    ['Applied context resets',value.context_resets??'—'],
    ['Checkpoint tool calls',value.checkpoint_calls??'—'],
    ['read_file calls',value.read_calls??'—']
  ];
  $('cost-metrics').replaceChildren(...fields.map(([label,value])=>{
    const item=node('div',undefined,'metric');item.append(node('strong',value),node('span',label));return item;
  }));
  const c=value.coverage;
  $('cost-coverage').textContent=c?`Full-trial coverage: ${c.timed_requests}/${c.requests} request timings; ${c.responses}/${c.requests} responses; backend prefill/generation reports ${c.backend_prompt_reports}/${c.backend_decode_reports}. ${c.trajectory_available?'Tool counts use the latest saved trajectory.':'Saved trajectory unavailable; tool counts/edit times unknown.'}${c.trajectory_truncated?' Trajectory exceeds the display reader’s size bound.':''}`:'';
  $('cost-note').textContent=value.note||'';
}
function delegatedMetrics(run,trace){
  const job=run.delegation, result=job?.result?.result, summary=trace?.summary;
  const check=result?.checks_passed??summary?.independent_checks_passed;
  return [['Use',job?.classification?.kind==='lifecycle_acceptance'?'LIFECYCLE CHECK':job?.classification?.kind==='diagnostic_replay'?'DIAGNOSTIC REPLAY':'USEFUL WORK'],['Execution',job?.state?.state||run.state],
    ['Independent checks',check===true?'PASS':check===false?'FAIL':'UNVERIFIED'],
    ['Clean model completion',summary?.clean_agent_completion===true?'YES':summary?'NO':'PENDING'],
    ['Outer acceptance',(job?.outer_review?.decision||'PENDING').replaceAll('_',' ')],
    ['Applied',job?.application?.applied===true?'YES':'NO'],
    ['Dispatch to artifact',secs(job?.result?.dispatch_seconds)],
    ['Worker task time',secs(summary?.task_wall_seconds)],
    ['Cleanup',job?.state?.cleanup_verified===true?'VERIFIED':'PENDING']];
}
function jobDetails(run){
  const delegated=run.kind==='delegated';
  $('job-details').hidden=!delegated;
  $('outcome-title').textContent=delegated?'Worker result and unverified handoff':'Verified outcome';
  $('diff-title').textContent=delegated?'Original worker patch · outer repairs are recorded separately':'Final patch';
  $('job-evidence').textContent=delegated?json(run.delegation||{status:'Preparing durable job evidence'}):'';
  $('record-type').textContent=delegated?(run.delegation?.classification?.kind==='lifecycle_acceptance'?'DELEGATION LIFECYCLE ACCEPTANCE':'DELEGATED REPOSITORY WORK'):run.kind==='continuation'?'CONTROLLED CONTINUATION EXPERIMENT':'EXPERIMENT RECORD';
  $('timing-note').textContent=delegated?'Dispatch includes setup, task, verification and cleanup; outer review is separate':run.kind==='continuation'?'Timings begin at a saved boundary; earlier work and priming are reported separately':'Refreshes every 2 seconds · task timing excludes model loading';
}
function render(run,trace){const scope=json([run.name,state.trial]);if(scope!==state.artifactScope){resetArtifact();state.artifactScope=scope;}if(scope===state.eventScope){for(const row of document.querySelectorAll('details.event'))state.eventOpen.set(row.dataset.event,row.open);for(const d of document.querySelectorAll('details.event details'))state.eventNested.set(json([d.closest('.event').dataset.event,d.querySelector('summary').textContent]),d.open);}else{state.eventOpen.clear();state.eventNested.clear();state.eventScope=scope;}const beforeOpen=new Set([...state.eventOpen].filter(([,open])=>open).map(([id])=>id));const nestedOpen=[...state.eventNested].filter(([,open])=>open).map(([key])=>JSON.parse(key));eventNavigation(trace);handoffEvidence(trace?.summary?.final_handoff);costBreakdown(trace?.cost_breakdown);jobDetails(run);const closeToBottom=state.signature&&window.innerHeight+window.scrollY>=document.body.scrollHeight-160;const scroll=window.scrollY;$('title').textContent=run.delegation?.label||run.name;$('subtitle').textContent=[run.model||'Preparing model',run.protocol||(run.kind==='control'?'Parser-only control':'Original MVP protocol'),run.kind==='continuation'?'Controlled fixed-world continuations; original budgets retained':run.budget?`${run.budget}s task ceiling`:''].filter(Boolean).join(' · ');$('run-state').textContent=run.state;$('run-state').className=`badge ${statusClass(run.state)}`;
const current=run.trials.find(t=>t.name===state.trial);const summary=trace?.summary;const control=current?.kind==='control';const adjudication=current?.adjudication??trace?.outer_adjudication??summary?.task_adjudication;const pending=['pending_outer_rubric','pending_outer_review'].includes(adjudication?.status);const reviewed=adjudication?.status==='adjudicated';const blocker=reviewed&&adjudication?.disposition==='supported_blocker';const rejectedBlocker=reviewed&&adjudication?.disposition==='unsupported_blocker';const nonconforming=reviewed&&adjudication?.disposition==='nonconforming_run';const metrics=run.kind==='delegated'?delegatedMetrics(run,trace):current?.kind==='diagnostic'?diagnosticMetrics(current,adjudication):control?[['Control result',current?.passed===true?'PASS':current?.passed===false?'FAIL':'PENDING'],['Commands executed',current?.commands_executed??'PENDING'],['Control time',secs(current?.seconds)],['Service restoration',run.restored===true?'VERIFIED':run.restored===false?'FAILED':'PENDING']]:[[(blocker||rejectedBlocker)?'Blocker review':'Verified correctness',blocker?'SUPPORTED':rejectedBlocker?'UNSUPPORTED':nonconforming?'UNQUALIFIED':pending?'PENDING OUTER REVIEW':current?.correct===true?'PASS':current?.correct===false?'FAIL':'PENDING'],...(nonconforming?[['Runtime conformance','FAIL']]:[]),...(blocker?[['Canonical checks (diagnostic)',summary?.canonical_correctness===true?'SATISFIED':summary?.canonical_correctness===false?'NOT SATISFIED':'UNAVAILABLE','Coding checks are diagnostic for a supported blocker; a coding pass is not required.']]:((pending||reviewed)&&summary?.canonical_correctness!=null?[['Canonical checks'+(summary?.agent_outcome?.exit_status==='Blocked'?' (diagnostic)':''),summary?.canonical_correctness===true?'PASS':summary?.canonical_correctness===false?'FAIL':'PENDING']]:[])),[(pending||reviewed)&&summary?.agent_outcome?.exit_status==='Blocked'?'Clean halt':'Clean completion',(pending||reviewed)&&summary?.agent_outcome?.exit_status==='Blocked'?(summary?.clean_agent_halt===true?'YES':'NO'):current?.clean===true?'YES':current?.clean===false?'NO':'PENDING'],[current?.continuation?'Continuation time':'Task time',secs(current?.seconds),current?.continuation?'From sealed historical boundary; excludes prior work and inert cache priming. Not whole-task timing.':undefined],['Service restoration',run.restored===true?'VERIFIED':run.restored===false?'FAILED':'PENDING']];if(current?.comparison_review){const status=current.comparison_review.status;metrics.unshift(['Full-result review',status==='accepted'?'ACCEPTED':status==='rejected'?'REJECTED':status==='operationally_invalid'?'OPERATIONALLY INVALID':'PENDING',status==='operationally_invalid'?'Test scores below are preserved diagnostics; this attempt is excluded from model-quality comparisons.':'Source and handoff review is separate from canonical checks.']);}$('metrics').replaceChildren(...metrics.map(([label,value,note])=>{const m=node('div',undefined,'metric');m.append(node('strong',value),node('span',label));if(note)m.append(node('small',note));return m;}));
$('trials').replaceChildren(...run.trials.map(t=>{const b=node('button',undefined,`trial ${t.name===state.trial?'selected':''}`);b.append(node('span',t.kind==='control'?(t.control_kind||t.task):`${t.task}${t.continuation?` · ${t.continuation.arm}`:''} · seed ${t.seed??'pending'}`),badge(t.state),node('span',secs(t.seconds),'meta'));b.onclick=()=>select(run.name,t.name);return b;}));
$('events').replaceChildren(...(trace?.events.length?trace.events.map(e=>eventCard(e,beforeOpen.has(e.id))):[node('div','No model/tool events yet. Setup and server loading are visible in the Setup & restoration tab.','empty')]));for(const [id,title]of nestedOpen){for(const d of document.querySelectorAll('details.event details'))if(d.closest('.event').dataset.event===id&&d.querySelector('summary').textContent===title)d.open=true;}
$('trace-hint').textContent=trace?`${trace.events.length} displayed events${trace.event_window?.unreadable_requests?` · ${trace.event_window.unreadable_requests} unreadable request artifacts`:''} · ${control?(current.commands_executed===0?'parser control; commands were not executed':'parser control; see execution count'):(trace.events.some(e=>e.adapter_control)?'shell commands use disposable sandboxes; adapter controls execute no commands':'commands run in disposable sandboxes')} · click a row to inspect`:'Awaiting the first trial.';
$('outcome').textContent=summary?json(control?summary:{success:reviewed?(blocker?null:current?.passed):pending?null:summary.success,correct:reviewed?adjudication.coding_correctness:pending?null:summary.verified_correctness??summary.canonical_correctness,...((pending||reviewed)?{adjudication,raw_success:summary.success,raw_verified_correctness:summary.verified_correctness,blocker_claim:summary.spec_blocker_claim,clean_halt:summary.clean_agent_halt}:{}),...(summary.continuation?{continuation:summary.continuation,new_usage:summary.continuation_usage}:{}),model_handoff:summary.final_handoff,canonical_suite:summary.canonical_correctness,external_behavior:summary.behavioral_correctness,clean:summary.clean_agent_completion,interventions:summary.human_interventions,elapsed_seconds:summary.task_wall_seconds,outcome:summary.agent_outcome,error:summary.agent_error,verification:summary.verification,behavioral_verification:summary.behavioral_verification,verification_error:summary.verification_error}):'No verified result yet.';$('diff').textContent=control?'Parser controls do not produce a coding patch.':(trace?.diff||'No final patch yet.');const picked=$('artifact').value;$('artifact').replaceChildren(node('option','Choose an artifact…'),...(trace?.artifacts||[]).map(a=>{const o=node('option',a);o.value=a;return o;}));$('artifact').firstChild.value='';if((trace?.artifacts||[]).includes(picked))$('artifact').value=picked;$('config').textContent=json(run.config);$('lifecycle').textContent=json(run.lifecycle);$('server').textContent=run.server_tail||'Server log not available yet.';$('source').textContent=`/bulk/dlk/local-harness/runs/${run.name}${state.trial?'/experiment/'+state.trial:''}`;if($('follow').checked&&closeToBottom&&state.view==='timeline')window.scrollTo(0,document.body.scrollHeight);else window.scrollTo(0,scroll);}
async function refresh(force=false){
  if(state.busy){if(force)state.pending=true;return;}
  if(state.paused&&!force)return;
  state.busy=true;const revision=state.revision;
  try{
    const page=await api('runs',{page:state.page,page_size:state.pageSize,q:state.query});
    if(revision!==state.revision)return;
    state.pagination=page;state.page=page.page;state.runs=page.runs;
    if($('follow').checked||!state.run){if(state.run!==page.newest)resetEvents();state.run=page.newest;}
    runList();
    if(state.run){
      const run=await api('run',{run:state.run});if(revision!==state.revision)return;
      if($('follow').checked||!run.trials.some(t=>t.name===state.trial)){const trial=run.trials.at(-1)?.name||null;if(trial!==state.trial)resetEvents();state.trial=trial;}
      const trace=state.trial?await api('trace',{run:state.run,trial:state.trial,...(state.eventStart===null?{}:{start:state.eventStart})}):null;
      if(revision!==state.revision)return;
      const signature=json([run,trace]);if(signature!==state.signature){render(run,trace);state.signature=signature;}
    }
    $('connection').textContent=state.paused?'Updates paused':'● Connected · read-only';
    $('updated').textContent=`Updated ${new Date().toLocaleTimeString()}`;$('error').hidden=true;
  }catch(e){
    if(revision!==state.revision)return;
    $('connection').textContent='Disconnected';$('error').hidden=false;
    $('error').textContent=`Could not refresh: ${e.message}. Existing evidence remains visible; retrying.`;
  }finally{state.busy=false;if(state.pending){state.pending=false;refresh(true);}}
}
let filterTimer;
$('filter').addEventListener('input',()=>{
  clearTimeout(filterTimer);state.revision++;
  filterTimer=setTimeout(()=>{state.query=$('filter').value;state.page=1;requestRefresh();},200);
});
$('older-events').onclick=()=>changeEventPage('older');
$('newer-events').onclick=()=>changeEventPage('newer');
$('latest-events').onclick=()=>changeEventPage('latest');
$('previous-page').onclick=()=>changePage(state.page-1);
$('next-page').onclick=()=>changePage(state.page+1);
$('pause').onclick=()=>{state.paused=!state.paused;$('pause').textContent=state.paused?'Resume updates':'Pause updates';if(state.paused)$('connection').textContent='Updates paused';else refresh();};
$('follow').onchange=()=>{state.signature='';if($('follow').checked){resetEvents();state.page=1;state.query='';$('filter').value='';clearTimeout(filterTimer);}requestRefresh();};
for(const tab of document.querySelectorAll('.tab'))tab.onclick=()=>{state.view=tab.dataset.tab;for(const b of document.querySelectorAll('.tab')){b.classList.toggle('active',b===tab);b.setAttribute('aria-selected',String(b===tab));}for(const id of ['timeline','result','setup'])$(id).hidden=id!==state.view;};function resetArtifact(){state.artifactRevision++;$('raw').textContent='Select a recorded artifact. Display is bounded; complete evidence remains on disk.';}
$('artifact').onchange=()=>resetArtifact();
$('load-artifact').onclick=async()=>{
  if(!state.trial||!$('artifact').value)return;
  const selection={run:state.run,trial:state.trial,name:$('artifact').value};
  const revision=++state.artifactRevision;
  const current=()=>revision===state.artifactRevision&&selection.run===state.run&&selection.trial===state.trial&&selection.name===$('artifact').value;
  $('raw').textContent=`Loading ${selection.name}…`;
  try{const d=await api('artifact',selection);if(current())$('raw').textContent=d.text+(d.truncated?'\n\n[Display truncated; full artifact is on disk.]':'');}
  catch(e){if(current())$('raw').textContent=e.message;}
};refresh();setInterval(()=>refresh(),2000);
