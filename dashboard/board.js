/* Decision Ledger's own UI root only. No core markup, stores or prototypes are accessed. */
(function () {
  'use strict';
  const words = {proposed:'Awaiting your review',approved:'Confirmed scope',conditional:'Conditions remain',rejected:'Not accepted',revoked:'Withdrawn',superseded:'Replaced'};
  function el(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=String(text).replace(/[\p{Cf}\u0000-\u0008\u000b-\u001f\u007f-\u009f]/gu,c=>'\\u'+c.codePointAt(0).toString(16).toUpperCase().padStart(4,'0')); return n; }
  function mount(root, fetchReceipts, fixture=false) {
    let rows=[], total=0, next=null, selected=null, filter='all', query='', alive=true;
    root.className='dl';
    const shell=el('div','dl-shell'); root.append(shell);
    const top=el('header','dl-top');top.append(el('div','dl-brand','D / L'),el('span','dl-eyebrow','DECISION LEDGER'),el('span','dl-local',fixture?'SAMPLE DATA · PREVIEW':'PROFILE-LOCAL · READ ONLY'));shell.append(top);
    const hero=el('section','dl-hero'); const title=el('div');title.append(el('p','dl-eyebrow','KEEP THE AGREEMENT. LOSE THE GUESSWORK.'),el('h1','','What you agreed.\nNothing extra.'),el('p','dl-intro','A proposal is a possibility. A confirmed receipt records the exact scope you reviewed.'));hero.append(title);
    const legend=el('div','dl-legend');[['01','Propose','Capture the exact scope.'],['02','Review','You make the decision.'],['03','Recall','Carry the receipt forward.']].forEach(([n,t,d])=>{const x=el('div');x.append(el('span','dl-step',n),el('strong','',t),el('span','',d));legend.append(x);});hero.append(legend);shell.append(hero);
    const toolbar=el('div','dl-toolbar');const tabs=el('div','dl-tabs'); const buttons={};
    [['all','All decisions'],['approved','Confirmed'],['proposed','Proposed'],['history','Past decisions']].forEach(([k,t])=>{const b=el('button','',t);b.type='button';b.onclick=()=>{filter=k;render();};buttons[k]=b;tabs.append(b);});
    const search=el('input','dl-search');search.type='search';search.placeholder='Find a project, topic or scope';search.setAttribute('aria-label','Search loaded decisions');search.oninput=()=>{query=search.value.toLowerCase();render();};
    const refresh=el('button','dl-refresh','Refresh');refresh.onclick=()=>load(false);toolbar.append(tabs,search,refresh);shell.append(toolbar);
    const message=el('div','dl-message');message.setAttribute('role','status');shell.append(message);
    const layout=el('div','dl-layout'), list=el('div','dl-list'), detail=el('section','dl-detail');detail.setAttribute('aria-label','Selected decision');layout.append(list,detail);shell.append(layout);
    const footer=el('footer','dl-footer');footer.append(el('span','','A decision record, not an execution firewall.'),el('span','','Missing receipts mean unknown. Other direct instructions still matter.'));shell.append(footer);
    const format=d=>{const x=new Date(d);return Number.isNaN(x.getTime())?'Date unavailable':x.toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric',hour:'2-digit',minute:'2-digit'});};
    function chip(status){return el('span','dl-chip dl-'+status,status==='approved'?'CONFIRMED':status.toUpperCase());}
    function render(){
      if(!alive)return;Object.entries(buttons).forEach(([k,b])=>{b.classList.toggle('active',filter===k);b.setAttribute('aria-pressed',String(filter===k));});
      const visible=rows.filter(r=>(filter==='all'||(filter==='history'?['rejected','revoked','superseded'].includes(r.status):r.status===filter))&&[r.project,r.topic,r.scope].join(' ').toLowerCase().includes(query));
      list.replaceChildren();const count=el('p','dl-count',`${rows.length} of ${total} records loaded · ${visible.length} shown`);list.append(count);
      visible.forEach(r=>{const b=el('button','dl-receipt'+(r.id===selected?' selected':''));b.type='button';b.setAttribute('aria-label',r.project+' / '+r.topic+' — '+r.status);b.onclick=()=>{selected=r.id;render();};const head=el('div','dl-row');head.append(el('span','dl-project',r.project),chip(r.status));b.append(head,el('h2','',r.topic.replace(/[-_]/g,' ')),el('p','dl-scope-preview',r.scope),el('div','dl-card-foot',words[r.status]||r.status));list.append(b);});
      if(!visible.length)list.append(el('div','dl-empty','No matching decisions. Try another search or filter.'));
      if(next!==null){const more=el('button','dl-refresh','Load more records');more.onclick=()=>load(true);list.append(more);}
      const r=visible.find(r=>r.id===selected)||visible[0];if(r)selected=r.id;detail.replaceChildren();
      if(!r){detail.append(el('p','dl-eyebrow','YOUR NEXT CLEAR DECISION'),el('h2','','Start with a scope.'),el('p','','Ask Hermes to draft a Decision Ledger proposal with a project, topic and exact scope. It stays proposed until you review and confirm.'),el('p','dl-note','Natural capture is not automatic. Ask for Decision Ledger explicitly.'));return;}
      const dh=el('div','dl-row');dh.append(el('p','dl-eyebrow','RECEIPT / '+r.id),chip(r.status));detail.append(dh,el('h2','dl-detail-title',r.topic.replace(/[-_]/g,' ')),el('p','dl-subtitle',r.project+' · '+words[r.status]));
      const exact=el('div','dl-exact');exact.append(el('p','dl-eyebrow','EXACT RECORDED SCOPE'),el('p','dl-scope',r.scope));detail.append(exact);
      if(r.status==='proposed')detail.append(el('p','dl-note','No operator receipt yet. This proposal does not add permission or cancel authorization you gave elsewhere.'));
      if(r.status==='approved')detail.append(el('p','dl-note','Confirmed by a local operator action. Read the exact scope and exclusions above; this is not permission for additional work.'));
      if(r.status==='conditional')detail.append(el('p','dl-note','The operator accepted this scope with conditions. Their fulfillment has not yet been attested.'));
      if(r.conditions.length){const cs=el('section','dl-conditions');cs.append(el('h3','','Conditions'));r.conditions.forEach(c=>cs.append(el('p','',c)));cs.append(el('small','','Condition attestations are statements, not independently verified tests.'));detail.append(cs);}
      const hist=el('section','dl-history');hist.append(el('h3','','Decision trail'));const items=[{action:'proposed',created_at:r.created_at},...r.events];items.forEach(e=>{const x=el('div','dl-event');const labels={proposed:'Proposal recorded',approve:'Scope confirmed',reject:'Proposal rejected',revoke:'Receipt withdrawn',supersede:'Receipt replaced',satisfy:'Conditions attested'};x.append(el('span','dl-dot'),el('strong','',labels[e.action]||e.action),el('time','',format(e.created_at)));hist.append(x);});detail.append(hist);
      if(r.source_attached)detail.append(el('p','dl-note','Historical source attached. This page does not reverify the original conversation.'));
      const token=el('div','dl-token');token.append(el('p','dl-eyebrow','EXACT TOKEN'),el('code','',r.token));detail.append(token);
      if(r.status==='proposed'){const review=el('div','dl-review');review.append(el('h3','','Your review. Your decision.'),el('p','','Open the bundled operator_console.py in a separate foreground terminal as the profile data owner. At its operator prompt, enter:'),el('code','','approve '+r.token),el('p','','Inspect the full preview. Personally type confirm REVIEW_CODE in that same session only if you agree. Gateway slash approvals are refused.'));detail.append(review);}
    }
    async function load(append){message.textContent='Reading your ledger…';refresh.disabled=true;try{const data=await fetchReceipts(append?next:0);if(!alive)return;rows=append?[...rows,...data.decisions]:data.decisions;total=data.total;next=data.next_offset;message.textContent=fixture?'Design preview with synthetic records. No live receipts or approvals.':'Read from your ledger. Refresh to see later changes; search covers loaded records.';render();}catch(error){if(!alive)return;message.textContent='Could not read the ledger. No records were changed. Try Refresh.';/* Keep last readable receipt visible, marked stale. */if(rows.length)message.textContent+=' Previously loaded records may be out of date.';}finally{refresh.disabled=false;}}
    load(false);return ()=>{alive=false;root.replaceChildren();};
  }
  window.DecisionLedgerBoard={mount};
  const sdk=window.__HERMES_PLUGIN_SDK__;
  if(sdk&&window.__HERMES_PLUGINS__){const R=sdk.React;function Board(){const ref=R.useRef(null);R.useEffect(()=>mount(ref.current,offset=>sdk.fetchJSON('/api/plugins/decision-ledger/receipts?offset='+offset)),[]);return R.createElement('div',{ref});}window.__HERMES_PLUGINS__.register('decision-ledger',Board);}
})();
