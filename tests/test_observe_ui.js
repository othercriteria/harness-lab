// Offline render regression: no browser, server, network or artifact execution.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor() { this.children=[]; this.dataset={}; this.value=''; this.checked=false; this.classList={toggle(){}}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; }
  get firstChild() { return this.children[0]; }
  set innerHTML(value) { throw new Error("HTML interpretation forbidden"); }
  set href(value) { throw new Error("Model links forbidden"); }
  addEventListener(name,fn) { this[name]=fn; }
  setAttribute() {}
}
const elements=new Map();
const document={
  getElementById(id) { if(!elements.has(id))elements.set(id,new Element()); return elements.get(id); },
  createElement(tag) { const element=new Element();element.tag=tag;return element; },
  createDocumentFragment() { return new Element(); },
  querySelectorAll() { return []; },
  body:{scrollHeight:1000},
};
const context=vm.createContext({document,window:{innerHeight:800,scrollY:0,scrollTo(){}},
  fetch:()=>new Promise(()=>{}),setInterval(){},setTimeout,clearTimeout,URLSearchParams});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../observatory/app.js'),'utf8'),context);
const text=e=>[e.textContent??'',...e.children.map(text)].join(' ');
const run={name:'parser-control',kind:'control',state:'complete',restored:true,trials:[{
  name:'trial-00-control',kind:'control',passed:true,commands_executed:0,seconds:203.7,
  state:'passed',control_kind:'inert long-prefix control',task:'probe',
}]};
const trace={kind:'control',summary:{kind:'inert long-prefix control',passed:true,
  commands_executed:0,cases:[{name:'long_prefix_bounded64'}]},artifacts:[],events:[{
  id:'long_prefix_bounded64',kind:'model',state:'returned',finish:'tool_calls',
  usage:{prompt_tokens:20568,completion_tokens:97},seconds:203.7,tool_calls:[],
  control_case:{name:'long_prefix_bounded64',parse_valid:true},
}]};
context.input={run,trace};
vm.runInContext("state.trial='trial-00-control';render(input.run,input.trace)",context);
assert.match(text(elements.get('metrics')),/PASS Control result/);
assert.match(text(elements.get('metrics')),/0 Commands executed/);
assert.doesNotMatch(text(elements.get('metrics')),/Canonical|Verified correctness|Clean completion/);
assert.match(text(elements.get('events')),/long_prefix_bounded64/);
assert.match(text(elements.get('events')),/20568/);
assert.match(elements.get('trace-hint').textContent,/commands were not executed/);
assert.equal(JSON.parse(elements.get('outcome').textContent).passed,true);
assert.match(elements.get('diff').textContent,/do not produce a coding patch/);
run.kind='coding'; Object.assign(run.trials[0],{kind:'coding',correct:true,clean:false});
trace.summary={success:false,canonical_correctness:true,clean_agent_completion:false};
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/PASS Verified correctness/);
assert.match(text(elements.get('metrics')),/NO Clean completion/);
console.log('Observatory control and coding render checks passed.');

// Checkpoint memory is a nonterminal adapter event; model text stays inert.
context.checkpointEvent={id:'tool-002',kind:'tool',tool_name:'checkpoint_context',
  adapter_control:true,checkpoint_control:'summary_saved',executed:false,
  cleanup_required:false,state:'checkpoint saved / unverified memory',
  arguments:{summary:'<script>untrusted</script>'},result:{ok:true}};
const checkpointCard=vm.runInContext('eventCard(checkpointEvent,true)',context);
assert.match(text(checkpointCard),/CHECKPOINT/);
assert.match(text(checkpointCard),/unverified memory/);
assert.match(text(checkpointCard),/not submitted/);
assert.doesNotMatch(text(checkpointCard),/FINALIZE|BASH/);

// Pilot-wide pending verdict must override raw false for Submitted and Blocked.
Object.assign(run.trials[0],{correct:false,clean:true,adjudication:{status:'pending_outer_rubric'}});
Object.assign(trace.summary,{verified_correctness:false,task_adjudication:{status:'pending_outer_rubric',correct:null},agent_outcome:{exit_status:'Submitted'},clean_agent_halt:true});
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/PENDING OUTER REVIEW Verified correctness/);
assert.match(text(elements.get('metrics')),/PASS Canonical checks/);
assert.doesNotMatch(text(elements.get('metrics')),/FAIL Verified correctness/);
assert.equal(JSON.parse(elements.get('outcome').textContent).correct,null);
assert.equal(JSON.parse(elements.get('outcome').textContent).raw_verified_correctness,false);
trace.summary.agent_outcome.exit_status='Blocked';trace.summary.canonical_correctness=false;run.trials[0].clean=false;
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/PENDING OUTER REVIEW Verified correctness/);
assert.match(text(elements.get('metrics')),/FAIL Canonical checks \(diagnostic\)/);
assert.match(text(elements.get('metrics')),/YES Clean halt/);
delete run.trials[0].adjudication; delete trace.summary.task_adjudication;
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/FAIL Verified correctness/);
console.log('Pending Submitted/Blocked and legacy failure rendering checks passed.');

// Reviewed coding and blocker outcomes remain distinct from immutable raw scores.
run.trials[0].adjudication={status:'adjudicated',disposition:'verified_coding',coding_correctness:true};
run.trials[0].correct=true;run.trials[0].passed=true;run.trials[0].clean=true;
trace.summary.agent_outcome.exit_status='Submitted';trace.summary.canonical_correctness=true;
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/PASS Verified correctness/);
assert.equal(JSON.parse(elements.get('outcome').textContent).raw_success,false);
assert.equal(JSON.parse(elements.get('outcome').textContent).correct,true);
run.trials[0].adjudication={status:'adjudicated',disposition:'supported_blocker',coding_correctness:null};
run.trials[0].correct=null;run.trials[0].passed=null;run.trials[0].clean=false;
trace.summary.agent_outcome.exit_status='Blocked';trace.summary.canonical_correctness=false;
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/SUPPORTED Blocker review/);
assert.doesNotMatch(text(elements.get('metrics')),/PASS Verified correctness/);
assert.equal(JSON.parse(elements.get('outcome').textContent).success,null);
console.log('Separate outer coding and blocker verdict rendering checks passed.');
run.trials[0].adjudication={status:'adjudicated',disposition:'unsupported_blocker',coding_correctness:false,task_handling_correctness:false};
run.trials[0].state='unsupported blocker';run.trials[0].correct=false;run.trials[0].passed=false;
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/UNSUPPORTED Blocker review/);
assert.doesNotMatch(text(elements.get('metrics')),/PENDING OUTER REVIEW/);
assert.equal(JSON.parse(elements.get('outcome').textContent).success,false);
assert.equal(JSON.parse(elements.get('outcome').textContent).raw_success,false);
assert.equal(vm.runInContext('runOutcomeSummary(input.run)',context),'1 failed trial');
assert.equal(vm.runInContext("statusClass('unsupported blocker')",context),'bad');
console.log('Unsupported blocker is reviewed failure, not pending or supported.');

run.trials[0].adjudication={status:'adjudicated',review_kind:'posthoc_contract',disposition:'failed_coding',coding_correctness:false,task_handling_correctness:false};
run.trials[0].state='failed';run.trials[0].clean=true;
trace.summary={success:true,verified_correctness:true,canonical_correctness:true,behavioral_correctness:true,clean_agent_completion:true,clean_agent_halt:true,agent_outcome:{exit_status:'Submitted'}};
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/FAIL Verified correctness/);
assert.match(text(elements.get('metrics')),/PASS Canonical checks/);
assert.match(text(elements.get('metrics')),/YES Clean completion/);
assert.equal(JSON.parse(elements.get('outcome').textContent).raw_success,true);
assert.equal(JSON.parse(elements.get('outcome').textContent).raw_verified_correctness,true);
assert.equal(JSON.parse(elements.get('outcome').textContent).correct,false);
assert.equal(vm.runInContext('runOutcomeSummary(input.run)',context),'1 failed trial');
console.log('Post-hoc contract failure retains frozen passing test scores.');


context.input.run.kind='coding';context.input.run.trials=[
 {state:'passed',adjudication:{status:'adjudicated'}},{state:'supported blocker',adjudication:{status:'adjudicated'}},
 {state:'supported blocker',adjudication:{status:'adjudicated'}},{state:'passed',adjudication:{status:'adjudicated'}}];
assert.equal(vm.runInContext('runOutcomeSummary(input.run)',context),'2 coding passes · 2 supported blockers');
context.input.run.trials[1]={state:'blocked claim / unadjudicated',adjudication:{status:'pending_outer_rubric'}};
context.input.run.trials[2]={state:'unsafe cleanup / stopped',adjudication:{status:'pending_outer_rubric'}};
assert.equal(vm.runInContext('runOutcomeSummary(input.run)',context),'2 coding passes · 1 awaiting review · 1 stopped trial');
context.input.run.trials=[{state:'passed'},{state:'failed'}];
assert.equal(vm.runInContext('runOutcomeSummary(input.run)',context),'1/2 trials passed');
context.input.run.kind='control';assert.equal(vm.runInContext('runOutcomeSummary(input.run)',context),'1/2 controls passed');
console.log('Mixed outcome counts and legacy counts passed.');

// Server page metadata retains exact totals without putting all rows in the UI.
context.campaigns=Array.from({length:20},(_,i)=>({name:`campaign-${i}`,state:'complete',trials:[]}));
vm.runInContext("state.runs=campaigns;state.pagination={total:106,matching:106,page:1,pages:6,page_size:20,query:''};runList()",context);
assert.equal(elements.get('run-count').textContent,'106');
assert.equal(elements.get('runs').firstChild.children.length,20);
assert.match(elements.get('page-info').textContent,/1–20 of 106/);
assert.equal(elements.get('previous-page').disabled,true);
assert.equal(elements.get('next-page').disabled,false);
vm.runInContext("state.runs=[{name:'campaign-105',state:'complete',trials:[]}];state.pagination={total:106,matching:1,page:1,pages:1,page_size:20,query:'CAMPAIGN-105'};runList()",context);
assert.equal(elements.get('run-count').textContent,'1 / 106');
assert.match(text(elements.get('runs')),/campaign-105/);
assert.equal(elements.get('next-page').disabled,true);
vm.runInContext("state.runs=[];state.pagination.matching=0;state.run='selected-older';runList()",context);
assert.equal(elements.get('run-count').textContent,'0 / 106');
assert.match(text(elements.get('runs')),/No matching campaigns/);
assert.match(elements.get('selected-campaign').textContent,/selected-older/);
assert.equal(elements.get('selected-campaign').hidden,false);
console.log('Paginated count, empty search, controls and off-page selection passed.');

// Genuine finalization renders one shared text-only handoff for both dispositions.
const hostile='<img src=x onerror=globalThis.pwned=1> javascript:alert(1) /etc/passwd';
const allTags=e=>[e.tag,...e.children.flatMap(allTags)];
for(const disposition of ['submitted','blocked']) {
  const terminal=disposition==='submitted'?'Submitted':'Blocked';
  const handoff={disposition,summary:hostile,evidence:[{kind:'public_contract',public_clause:hostile,supports:'Unverified argument.'}],unverified:['Not independently checked.'],blocker:disposition==='blocked'?{category:'open_problem',argument:hostile,necessary_change:'Weaken obligation.'}:null};
  const projection={status:'unverified_model_handoff',source:'model',handoff,observation_count:0,observations_artifact:'final-handoff.json'};
  inputRunReset();
  trace.summary={success:false,canonical_correctness:false,verified_correctness:false,clean_agent_completion:disposition==='submitted',clean_agent_halt:true,task_adjudication:{status:'pending_outer_rubric'},agent_outcome:{exit_status:terminal},final_handoff:projection};
  trace.events=[{id:'tool-002',kind:'tool',state:'adapter terminal / '+terminal,tool_name:'finish_attempt',adapter_control:true,arguments:handoff,executed:false,terminal_control:terminal,cleanup_required:false,result:{ok:true,executed:false,terminal_control:terminal,cleanup_required:false},cleanup:null}];
  context.input={run,trace};vm.runInContext("state.trial='typed';render(input.run,input.trace)",context);
  const rendered=text(elements.get('events'));
  assert.match(rendered,/FINALIZE/);assert.match(rendered,/finish_attempt/);assert.match(rendered,/Model handoff \(unverified\)/);
  assert.match(rendered,/No shell command executed/);assert.doesNotMatch(rendered,/BASH|verified.*true|returncode|stdout/);
  assert.ok(rendered.includes(hostile));assert.equal(context.pwned,undefined);
  assert.ok(!allTags(elements.get('events')).some(t=>['a','img','script','iframe'].includes(t)));
  assert.deepEqual(JSON.parse(elements.get('outcome').textContent).model_handoff,projection);
  assert.match(elements.get('trace-hint').textContent,/adapter controls execute no commands/);
}
function inputRunReset(){run.kind='coding';run.trials=[{name:'typed',task:'synthetic',kind:'coding',state:'submitted / unadjudicated',adjudication:{status:'pending_outer_rubric'}}];}
console.log('Typed submitted/blocked text-only handoff, no execution/cleanup fiction passed.');

// Exact edits display arguments as inert text and retain real sandbox cleanup.
trace.events=[{id:'tool-003',kind:'tool',state:'returned',tool_name:'edit_file',adapter_control:false,arguments:{path:'a.py',old_text:hostile,new_text:'new'},command:null,result:{ok:true,returncode:0,stdout:'{"changed":true}',stderr:''},cleanup:{verified:true,active_state:'inactive'}}];
context.input={run,trace};vm.runInContext("render(input.run,input.trace)",context);
const editRendered=text(elements.get('events'));
assert.match(editRendered,/EDIT/);assert.match(editRendered,/Exact edit arguments/);assert.match(editRendered,/Cleanup/);
assert.doesNotMatch(editRendered,/FINALIZE|BASH|No new sandbox cleanup receipt/);
assert.ok(editRendered.includes(hostile));assert.equal(context.pwned,undefined);
assert.ok(!allTags(elements.get('events')).some(t=>['a','img','script','iframe'].includes(t)));
console.log('Exact edit arguments and real cleanup render as inert text.');

// Snapshot reads are not shell executions; preserve actual visible contents,
// duplicate references, failures and pending requests without inventing cleanup.
for(const variant of ['contents','reference','failure','pending']) {
  const output=variant==='reference'?'Unchanged range at o0001':variant==='failure'?'File does not exist':`4: ${hostile}\n5: print('ok')`;
  const visible={returncode:variant==='failure'?1:0,output,file_read:{path:'a.py',start_line:4,max_lines:20,contents_returned:variant!=='reference',context_observation_id:variant==='reference'?'o0001':undefined}};
  context.readEvent={id:'tool-003',kind:'tool',state:variant==='pending'?'reading':variant==='failure'?'read failed':'read returned',tool_name:'read_file',read_only:true,arguments:{path:'a.py',start_line:4,max_lines:20},result:variant==='pending'?null:{ok:variant!=='failure',executed:false,read_only:true,cleanup_required:false,wall_seconds:0.0003,visible},cleanup:null};
  const card=vm.runInContext('eventCard(readEvent,true)',context);
  const rendered=text(card);
  assert.match(rendered,/READ/);assert.match(rendered,/a.py/);assert.match(rendered,/from line 4/);
  assert.doesNotMatch(rendered,/BASH|FINALIZE|stdout|Cleanup/);
  if(variant!=='pending'){
    assert.ok(rendered.includes(output));assert.match(rendered,/Read-only workspace snapshot inspection/);
    assert.match(rendered,variant==='reference'?/Existing context reference/:/Returned text/);
  }
  assert.equal(context.pwned,undefined);
  assert.ok(!allTags(card).some(t=>['a','img','script','iframe'].includes(t)));
}
context.unknownEvent={id:'tool-099',kind:'tool',state:'returned',tool_name:'future_tool',arguments:{query:hostile}};
const unknownCard=vm.runInContext('eventCard(unknownEvent,true)',context);
assert.match(text(unknownCard),/TOOL/);assert.match(text(unknownCard),/future_tool/);
assert.doesNotMatch(text(unknownCard),/BASH/);assert.ok(text(unknownCard).includes(hostile));
console.log('Read-file contents/references/failures/pending and unknown-tool fallback passed.');

// Closed unanswered calls are visibly terminal, with unavailable usage made explicit.
for (const endedState of ['attempt deadline reached','request timed out','attempt ended / response unavailable']) {
  context.endedEvent={id:'request-057',kind:'model',state:endedState,tool_calls:[],
    request_end:{reason:'Whole-stage wall deadline expired',response:'No readable response payload was recorded.',accounting:'Completed-response totals omit this request.'}};
  const card=vm.runInContext('eventCard(endedEvent,true)',context);
  assert.match(text(card),new RegExp(endedState));
  assert.match(text(card),/Request ended/);
  assert.match(text(card),/No readable response payload/);
  assert.match(text(card),/unknown output tokens/);
  assert.doesNotMatch(text(card),/awaiting response/);
  assert.equal(vm.runInContext('statusClass(endedEvent.state)',context),'bad');
}
assert.equal(vm.runInContext("statusClass('awaiting response')",context),'live');
console.log('Unanswered completed requests show end reason and unknown usage.');

// Decode one JSON argument layer for inspection; never interpret code/HTML or
// turn literal backslash-n in source into a real newline. Preserve raw evidence.
const oldText='def f():\n    return "\\n"\n'+hostile;
context.readableEvent={id:'request-edit',kind:'model',state:'returned',finish:'tool_calls',tool_calls:[
 {function:{name:'bash',arguments:JSON.stringify({command:'cat <<\'EOF\'\n'+oldText+'\nEOF'})}},
 {function:{name:'edit_file',arguments:JSON.stringify({path:'a.py',old_text:oldText,new_text:''})}},
]};
const readableCard=vm.runInContext('eventCard(readableEvent,true)',context);
const collectPre=e=>[...(e.tag==='pre'?[e.textContent]:[]),...e.children.flatMap(collectPre)];
assert.ok(collectPre(readableCard).includes(oldText));
assert.ok(collectPre(readableCard).includes(''));
assert.match(text(readableCard),/Empty string/);
assert.match(text(readableCard),/Raw requested tools \(API representation\)/);
assert.match(text(readableCard),/does not establish acceptance or execution/);
assert.equal(context.pwned,undefined);
assert.ok(!allTags(readableCard).some(t=>['a','img','script','iframe'].includes(t)));
context.readableEvent.tool_calls=[{function:{name:'edit_file',arguments:'{"old_text":'}}];
const malformedCard=vm.runInContext('eventCard(readableEvent,true)',context);
assert.match(text(malformedCard),/Not valid JSON/);
assert.match(text(malformedCard),/Raw requested tools/);
console.log('Decoded commands/edit strings preserve real newlines, literal escapes, empty replacements and raw malformed evidence.');

context.provisional={id:'tool-001',kind:'tool',adapter_control:true,tool_name:'finish_attempt',
  review_control:'fresh_context_requested',terminal_control:null,executed:false,cleanup_required:false,
  arguments:{disposition:'submitted'},state:'review requested / not submitted',
  result:{ok:true,review_control:'fresh_context_requested'}};
const reviewCard=vm.runInContext('eventCard(provisional,true)',context);
assert.match(text(reviewCard),/REVIEW/);
assert.match(text(reviewCard),/review requested; not submitted/);
assert.match(text(reviewCard),/"request_accepted": true/);
assert.doesNotMatch(text(reviewCard),/FINALIZE|adapter terminal/);
console.log('Provisional review control is not displayed as terminal acceptance.');

// Test-author diagnostics report oracle quality without implying a coding pass.
inputRunReset();
run.kind='diagnostic';
Object.assign(run.trials[0],{kind:'diagnostic',state:'diagnostic reviewed',clean:true,
  seconds:19.5,correct:null,passed:null,adjudication:{status:'adjudicated',
    disposition:'reviewed_diagnostic',coding_correctness:null,
    diagnostic_results:{sound_on_controls:true,incorrect_controls_detected:1,incorrect_controls_total:3}}});
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/REVIEWED Diagnostic review/);
assert.match(text(elements.get('metrics')),/1\/3 Defect detection/);
assert.match(text(elements.get('metrics')),/NONE Coding-goal credit/);
assert.doesNotMatch(text(elements.get('metrics')),/Verified correctness|PENDING OUTER REVIEW/);
assert.equal(vm.runInContext('runOutcomeSummary(input.run)',context),'1/1 diagnostics reviewed');
run.trials[0].adjudication.diagnostic_results.sound_on_controls=false;
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/FAIL Soundness controls/);
assert.match(text(elements.get('metrics')),/UNSOUND TESTS Defect detection/);
console.log('Diagnostic review remains separate from coding success.');
run.trials[0].diagnostic_kind='input-probe';
run.trials[0].adjudication.diagnostic_results={format_valid:true,inputs_valid:true,deterministic:true,difference_found:true};
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/FOUND Behavioral difference/);
assert.match(text(elements.get('metrics')),/NONE Coding-goal credit/);
assert.doesNotMatch(text(elements.get('metrics')),/Verified correctness|Defect detection|Soundness controls/);
run.trials[0].adjudication.diagnostic_results.inputs_valid=false;
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/UNQUALIFIED Behavioral difference/);

// A rejected runtime is not evidence that the submitted code is incorrect.
run.kind='coding';
Object.assign(run.trials[0],{kind:'coding',state:'runtime nonconformance',passed:false,correct:null,clean:true,
  adjudication:{status:'adjudicated',disposition:'nonconforming_run',coding_correctness:null,protocol_conforming:false}});
trace.summary={success:true,canonical_correctness:true,behavioral_correctness:true,clean_agent_completion:true};
vm.runInContext('render(input.run,input.trace)',context);
assert.match(text(elements.get('metrics')),/UNQUALIFIED Verified correctness/);
assert.match(text(elements.get('metrics')),/FAIL Runtime conformance/);
assert.match(text(elements.get('metrics')),/PASS Canonical checks/);
assert.equal(vm.runInContext('runOutcomeSummary(input.run)',context),'1 nonconforming run');
assert.equal(JSON.parse(elements.get('outcome').textContent).success,false);
assert.equal(JSON.parse(elements.get('outcome').textContent).raw_success,true);
assert.equal(vm.runInContext("statusClass('runtime nonconformance')",context),'bad');
console.log('Runtime nonconformance rejects acceptance while preserving raw checks.');

// Whole-file content is displayed literally in both requested and executed tools.
context.writeEvent={id:'tool-write',kind:'tool',state:'complete',tool_name:'write_file',
 arguments:{path:'a.py',content:oldText},result:{ok:true,returncode:0,stdout:'written'},cleanup:{verified:true}};
const writeCard=vm.runInContext('eventCard(writeEvent,true)',context);
assert.match(text(writeCard),/WRITE/);
assert.match(text(writeCard),/File write arguments/);
assert.ok(collectPre(writeCard).includes(oldText));
assert.ok(!allTags(writeCard).some(t=>['a','img','script','iframe'].includes(t)));
context.readableEvent.tool_calls=[{function:{name:'write_file',arguments:JSON.stringify({path:'empty.py',content:''})}}];
const writeRequest=vm.runInContext('eventCard(readableEvent,true)',context);
assert.ok(collectPre(writeRequest).includes(''));
assert.match(text(writeRequest),/Empty string/);
assert.equal(context.pwned,undefined);
console.log('Whole-file writes preserve literal contents and empty files in the trace display.');

// Checkpoint acceptance is distinct from submission, including pending calls.
for(const saved of [false,true]){
  context.polishCheckpoint={id:'tool-checkpoint',kind:'tool',tool_name:'checkpoint_context',adapter_control:true,arguments:{summary:hostile,evidence:[{observation_id:'o0010',supports:hostile}]},executed:false,state:saved?'checkpoint saved / unverified memory':'adapter pending',checkpoint_control:saved?'summary_saved':null,result:saved?{ok:true,stdout:'Budgets continue unchanged.'}:null};
  const card=vm.runInContext('eventCard(polishCheckpoint,true)',context);
  assert.match(text(card),/CHECKPOINT/);
  assert.doesNotMatch(text(card),/FINALIZE/);
  assert.match(text(card),/not submitted/);
  assert.match(text(card),saved? /"request_accepted": true/:/"request_accepted": null/);
  if(saved)assert.match(text(card),/Budgets continue unchanged/);
  assert.ok(text(card).includes(hostile));
}
context.snapshotEvent={id:'tool-scratch',kind:'tool',tool_name:'bash',state:'returned',result:{ok:true,snapshot:{files:14,file_bytes:46245},scratch_snapshot:{files:5,file_bytes:417}}};
const snapshotCard=vm.runInContext('eventCard(snapshotEvent,true)',context);
assert.match(text(snapshotCard),/Workspace snapshot/);
assert.match(text(snapshotCard),/Attempt scratch snapshot/);
assert.match(text(snapshotCard),/417/);
assert.match(text(snapshotCard),/excluded from the submitted workspace and evaluator/);
trace.event_window={total_requests:83,older_requests_omitted:3,unreadable_requests:1};
vm.runInContext('render(input.run,input.trace)',context);
assert.match(elements.get('trace-hint').textContent,/3 older requests omitted/);
assert.match(elements.get('trace-hint').textContent,/1 unreadable request artifacts/);
for(const state of ['read failed','transport stopped','attempt ended / tool receipt unavailable'])assert.equal(vm.runInContext(`statusClass('${state}')`,context),'bad');
assert.equal(vm.runInContext("statusClass('reading')",context),'live');
console.log('Checkpoint acceptance, scratch scope and incomplete timelines are explicit.');

// Exercise real asynchronous refresh/navigation, including stale responses.
async function paginationRefreshChecks(){
  const calls=[];
  let hold=null;
  context.fetch=async url=>{
    calls.push(url);
    const parsed=new URL(url,'http://localhost');
    if(parsed.pathname==='/api/runs'){
      if(hold){const waiting=hold;hold=null;return waiting;}
      const page=Number(parsed.searchParams.get('page'));
      const query=parsed.searchParams.get('q');
      return {ok:true,json:async()=>({runs:[{name:page===2?'older':'newest',state:'complete',trials:[]}],total:106,matching:query?1:106,page,pages:query?1:6,page_size:20,query,newest:'newest',unavailable:[]})};
    }
    return {ok:true,json:async()=>({name:parsed.searchParams.get('run'),trials:[]})};
  };
  context.rendered=[];
  vm.runInContext("render=(run)=>rendered.push(run.name);state.busy=false;state.pending=false;state.paused=false;state.run='selected-older';state.trial=null;state.signature='';state.page=2;state.query='';state.revision=0;",context);
  elements.get('follow').checked=false;
  await vm.runInContext('refresh()',context);
  assert.ok(calls[0].includes('page=2'));
  assert.ok(calls[1].includes('run=selected-older'));
  assert.equal(vm.runInContext('state.page',context),2);
  assert.equal(vm.runInContext('state.run',context),'selected-older');
  assert.equal(elements.get('selected-campaign').hidden,false);
  const list=elements.get('runs').firstChild;
  await vm.runInContext('refresh()',context);
  assert.equal(elements.get('runs').firstChild,list,'unchanged rows preserve focus/DOM');
  let release;
  hold=new Promise(resolve=>{release=resolve;});
  const oldRefresh=vm.runInContext('refresh()',context);
  vm.runInContext("select('clicked-during-refresh')",context);
  release({ok:true,json:async()=>({runs:[],newest:'stale-response'})});
  await oldRefresh;
  for(let i=0;i<20&&vm.runInContext('state.busy',context);i++)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(vm.runInContext('state.run',context),'clicked-during-refresh');
  assert.equal(context.rendered.at(-1),'clicked-during-refresh');
  assert.ok(!context.rendered.includes('stale-response'));
  vm.runInContext('state.paused=true',context);
  const before=calls.length;
  await vm.runInContext('refresh()',context);
  assert.equal(calls.length,before);
  vm.runInContext('changePage(3)',context);
  for(let i=0;i<20&&vm.runInContext('state.busy',context);i++)await new Promise(resolve=>setImmediate(resolve));
  assert.ok(calls.slice(before).some(url=>url.includes('page=3')));
  assert.equal(elements.get('connection').textContent,'Updates paused');
  elements.get('filter').value='CAMPAIGN-105';elements.get('filter').input();
  await new Promise(resolve=>setTimeout(resolve,250));
  assert.equal(vm.runInContext('state.page',context),1);
  assert.ok(calls.some(url=>url.includes('q=CAMPAIGN-105')));
  elements.get('follow').checked=true;elements.get('follow').onchange();
  for(let i=0;i<20&&vm.runInContext('state.busy',context);i++)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(vm.runInContext('state.run',context),'newest');
  assert.equal(vm.runInContext('state.query',context),'');
  assert.equal(vm.runInContext('state.page',context),1);
  // A late raw-artifact success or failure cannot populate a different selection.
  for(const reject of [false,true]){
    let deliver;
    context.fetch=()=>new Promise(resolve=>{deliver=resolve;});
    vm.runInContext("state.run='old';state.trial='trial-old'",context);
    elements.get('artifact').value='summary.json';
    const pending=elements.get('load-artifact').onclick();
    vm.runInContext("state.run='new';state.trial='trial-new';resetArtifact()",context);
    deliver({ok:!reject,json:async()=>reject?{error:'OLD ERROR'}:{text:'OLD EVIDENCE'}});
    await pending;
    assert.doesNotMatch(elements.get('raw').textContent,/OLD/);
  }
  context.fetch=async()=>({ok:true,json:async()=>({text:'CURRENT EVIDENCE'})});
  await elements.get('load-artifact').onclick();
  assert.equal(elements.get('raw').textContent,'CURRENT EVIDENCE');
  elements.get('artifact').value='changes.diff';elements.get('artifact').onchange();
  assert.doesNotMatch(elements.get('raw').textContent,/CURRENT EVIDENCE/);
  console.log('Refresh navigation and raw artifact selection reject stale replies.');
}
paginationRefreshChecks().catch(error=>{console.error(error);process.exitCode=1;});

// A supported impossibility argument does not excuse a materially false handoff.
assert.equal(vm.runInContext("statusClass('supported blocker / handoff failed')",context),'bad');
assert.match(vm.runInContext("runOutcomeSummary({kind:'coding',trials:[{state:'supported blocker / handoff failed',adjudication:{status:'adjudicated',task_handling_correctness:false}}]})",context),/1 failed trial/);

assert.equal(vm.runInContext("statusClass('correct code / handoff failed')",context),'bad');
assert.match(vm.runInContext("runOutcomeSummary({kind:'coding',trials:[{state:'correct code / handoff failed',correct:true,adjudication:{status:'adjudicated',task_handling_correctness:false}}]})",context),/1 failed trial/);
