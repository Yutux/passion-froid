'use strict';
const cfg=window.STUDIO, section=document.body.dataset.section;
const assets=JSON.parse(document.getElementById('asset-data').textContent);
const csrf=document.querySelector('[name=csrfmiddlewaretoken]').value;
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key=value=>value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toLowerCase();
const safeUrl=value=>{try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?esc(u.href):'';}catch{return '';}};
let filter='pending',limit=section==='dashboard'?4:12,tags=[],busy=false;
const drafts=new Map(assets.map(a=>[a.public_id,{title:a.gold_title||a.ai_title||a.nom_produit||a.nom_fichier||'Média sans titre',description:a.gold_description||a.ai_caption||'',tags:[...(a.tags_validated?a.gold_tags:a.ai_tags)||[]]}]));
let toastTimer;
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,8000);}
async function api(url,data,method='POST'){
 const response=await fetch(url,{method,headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(data)});
 let result;try{result=await response.json();}catch{throw Error('Réponse indisponible. Vérifiez votre connexion et votre session.');}
 if(!response.ok||result.error)throw Error(result.error||'Une erreur est survenue.');return result;
}
function image(a,cls){const url=safeUrl(a.url_gold||a.url_silver||a.url_bronze||a.url_image_source);return `<div class="${cls}">${url&&a.type_fichier==='image'?`<img src="${url}" alt="${esc(drafts.get(a.public_id).title)}" loading="lazy">`:'<span class="muted">Aperçu indisponible</span>'}</div>`;}
function badge(a){return a.tags_validated?'<span class="badge approved">✓ Validé</span>':a.ai_tag_source.startsWith('metadata-fallback')?'<span class="badge fallback">Métadonnées · analyse visuelle à faire</span>':a.media_status==='AI_ANALYZING'?'<span class="badge">✧ Analyse distante en cours</span>':a.ai_tag_source?'<span class="badge">✧ À vérifier</span>':'<span class="badge">Analyse à lancer</span>';}
function filtered(){const q=key($('media-search')?.value||'');return assets.filter(a=>{
 if(section==='learning'&&(a.type_fichier!=='image'||a.media_status==='ARCHIVED'||(filter==='validated')!==a.tags_validated))return false;
 if(section==='archives'&&a.media_status!=='ARCHIVED')return false;
 if(section==='assets'&&a.media_status==='ARCHIVED')return false;
 const d=drafts.get(a.public_id);return !q||key([d.title,a.reference,...d.tags].join(' ')).includes(q);
});}
function render(){const list=filtered(),grid=$('training-grid')||$('media-grid');if(!grid)return;
 grid.innerHTML=list.slice(0,limit).map(a=>{const d=drafts.get(a.public_id),idx=assets.indexOf(a);
 if(section!=='learning')return `<article class="media-card">${image(a,'media-image')}<div class="media-body"><h3 title="${esc(d.title)}">${esc(d.title)}</h3>${badge(a)}<div class="chips">${d.tags.slice(0,3).map(t=>`<span class="chip">${esc(t)}</span>`).join('')}</div><a class="text-link" href="${cfg.learning}?media=${encodeURIComponent(a.public_id)}">Ouvrir l’atelier →</a></div></article>`;
 return `<article class="training-card" data-index="${idx}" id="media-${idx}">${image(a,'training-image')}<div class="training-content">${badge(a)}<label for="title-${idx}">TITRE DU MÉDIA</label><input id="title-${idx}" class="title-input" maxlength="255" value="${esc(d.title)}" ${a.tags_validated?'readonly':''}><label for="description-${idx}">DESCRIPTION EN FRANÇAIS</label><textarea id="description-${idx}" class="description-input" maxlength="2500" ${a.tags_validated?'readonly':''}>${esc(d.description)}</textarea>${facetHtml(a)}<label>TAGS ${a.tags_validated?'VALIDÉS':'À AFFINER'}</label><div class="chips">${d.tags.map((t,i)=>`<span class="chip"><span>${esc(t)}</span>${a.tags_validated?'':`<button data-action="edit" data-tag="${i}" aria-label="Modifier ${esc(t)}">✎</button><button data-action="remove" data-tag="${i}" aria-label="Retirer ${esc(t)}">×</button>`}</span>`).join('')||'<span class="muted">Aucun tag. Lancez une analyse ou ajoutez vos tags.</span>'}</div>${a.tags_validated?'':`<form class="add-tag"><input aria-label="Nouveau tag" placeholder="Ajouter un tag…" maxlength="80" list="vocabulary"><button class="button" type="submit">＋ Ajouter</button></form>`}${a['analysis_job__error']?`<p class="job-error">${esc(a['analysis_job__error'])}</p>`:''}<p class="source">${esc(a.ai_tag_source.startsWith('metadata-fallback')?'Tags issus des informations produit, sans analyse visuelle.':a.ai_tag_source?'Source : '+a.ai_tag_source:'Aucune analyse pour le moment.')}</p><div class="card-actions">${a.tags_validated?'<span class="muted">✓ Validation enregistrée</span><button class="button" data-action="reopen">Corriger à nouveau</button>':'<button class="button" data-action="analyze">✧ Analyser</button><button class="button" data-action="save">Brouillon</button><button class="button primary" data-action="validate">✓ Valider et mémoriser</button>'}</div></div></article>`;
 }).join('')||'<div class="empty">Aucun média dans cette sélection.</div>';
 if($('load-more'))$('load-more').hidden=list.length<=limit;
 grid.querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>{img.parentElement.innerHTML='<span class="muted">Image indisponible</span>';},{once:true}));
}
function syncDraft(card){const d=drafts.get(assets[Number(card.dataset.index)].public_id);d.title=card.querySelector('.title-input').value;d.description=card.querySelector('.description-input')?.value||'';}
$('training-grid')?.addEventListener('input',e=>{const card=e.target.closest('[data-index]');if(card)syncDraft(card);});
$('training-grid')?.addEventListener('submit',e=>{e.preventDefault();const card=e.target.closest('[data-index]'),a=assets[Number(card.dataset.index)],input=e.target.querySelector('input'),v=input.value.trim();if(v)openFeedback(a,'add',v);});
$('training-grid')?.addEventListener('click',async e=>{const button=e.target.closest('[data-action]');if(!button)return;const card=button.closest('[data-index]'),a=assets[Number(card.dataset.index)],d=drafts.get(a.public_id),action=button.dataset.action,index=Number(button.dataset.tag);
 if(action==='remove'){openFeedback(a,'remove',d.tags[index]);return;}
 if(action==='edit'){openFeedback(a,'replace',d.tags[index]);return;}
 if(busy){toast('Une analyse est déjà en cours.');return;}
 button.disabled=true;const label=button.textContent;button.textContent='En cours…';
 try{if(action==='analyze'){await analyze(a);render();toast('Image ajoutée à la file. Les tags apparaîtront automatiquement.');}
 else if(action==='save'||action==='reopen'){const result=await api(cfg.draft,{public_id:a.public_id,...d});if(action==='reopen'){Object.assign(a,result.asset);a.tags_validated=false;filter='pending';document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x.dataset.filter===filter));render();}toast('Brouillon enregistré. Validez pour enrichir la mémoire.');}
 else{if(!d.title.trim()||!d.tags.length)throw Error('Renseignez un titre et au moins un tag.');const result=await api(cfg.validate.replace('__ID__',encodeURIComponent(a.public_id)),d);Object.assign(a,result.asset);render();toast(result.success?'Validation enregistrée. La mémoire a été enrichie.':'Validation locale enregistrée. La synchronisation distante reste à vérifier.');}}
 catch(error){toast(error.message);}finally{button.disabled=false;button.textContent=label;}
});
async function analyze(a){const result=await api(cfg.generate,{public_ids:[a.public_id],mode:'all',force_visual:true,async:true});if(!result.queued)throw Error('Un brouillon ou une validation protège ce média.');a.media_status='AI_ANALYZING';}

let stopBatch=false;
if($('analyze-batch')){
 const stop=document.createElement('button');stop.id='stop-batch';stop.className='button';stop.textContent='Arrêter après cette image';stop.hidden=true;
 $('batch-status').after(stop);stop.addEventListener('click',()=>{stopBatch=true;stop.disabled=true;stop.textContent='Arrêt en cours…';});
}
$('analyze-batch')?.addEventListener('click',async()=>{
 if(busy)return;
 busy=true;stopBatch=false;
 const button=$('analyze-batch'),stop=$('stop-batch');button.disabled=true;stop.hidden=false;stop.disabled=false;stop.textContent='Arrêter après cette image';
 const pending=assets.filter(a=>a.type_fichier==='image'&&!a.tags_validated&&a.media_status!=='ARCHIVED'&&(!a.ai_tag_source||a.ai_tag_source.startsWith('metadata-fallback')));
 let done=0,failed=0,consecutiveErrors=0;
 try{
  for(const a of pending){
   if(stopBatch)break;
   $('batch-status').textContent=`Analyse ${done+failed+1} / ${pending.length} · ${failed} échec(s)`;
   try{await analyze(a);done++;consecutiveErrors=0;}catch(error){failed++;consecutiveErrors++;toast(error.message);}
   render();
   if(consecutiveErrors>=3){stopBatch=true;toast('Lot mis en pause après 3 échecs consécutifs. Réessayez lorsque le fournisseur est disponible.');}
  }
 }finally{
  busy=false;button.disabled=false;stop.hidden=true;
  $('batch-status').textContent=`${stopBatch?'En pause':'Terminé'} : ${done} image(s) mise(s) en file, ${failed} échec(s), ${pending.length-done-failed} non traitée(s).`;
 }
});
$('media-search')?.addEventListener('input',()=>{limit=12;render();});
$('load-more')?.addEventListener('click',()=>{limit+=12;render();});
document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));limit=12;render();}));
async function loadTags(){const response=await fetch(cfg.tags);if(!response.ok)throw Error('Impossible de charger les tags.');tags=(await response.json()).tags;renderTags();let list=$('vocabulary');if(!list){list=document.createElement('datalist');list.id='vocabulary';document.body.append(list);}list.innerHTML=tags.filter(t=>t.active).map(t=>`<option value="${esc(t.name)}"></option>`).join('');}
function renderTags(){if(!$('tag-list'))return;const q=key($('tag-search').value);$('tag-list').innerHTML=tags.filter(t=>key(t.name+' '+t.category).includes(q)).map(t=>`<div class="tag-row ${t.active?'':'inactive'}"><span class="stat-icon violet" style="position:static;flex-shrink:0">⌗</span><div><strong>${esc(t.name)}</strong><small>${esc(t.category||'Sans famille')} ${t.active?'':'· Désactivé'}</small></div><button class="button" data-edit="${t.id}">${t.active?'Modifier':'Réactiver'}</button>${t.active?`<button class="button" data-delete="${t.id}">Supprimer</button>`:''}</div>`).join('')||'<p class="empty">Aucun tag. Créez votre premier tag ci-dessus.</p>';}
function resetTagForm(){$('tag-form').reset();$('tag-id').value='';$('tag-cancel').hidden=true;$('tag-form-title').textContent='Créer un tag';}
$('tag-form')?.addEventListener('submit',async e=>{e.preventDefault();const id=$('tag-id').value,button=e.submitter;button.disabled=true;try{await api(cfg.tags+(id?id+'/':''),{name:$('tag-name').value,category:$('tag-category').value},id?'PATCH':'POST');resetTagForm();await loadTags();toast('Tag enregistré.');}catch(error){toast(error.message);}finally{button.disabled=false;}});
$('tag-cancel')?.addEventListener('click',resetTagForm);$('tag-search')?.addEventListener('input',renderTags);
$('tag-list')?.addEventListener('click',async e=>{const button=e.target.closest('button');if(!button)return;const id=Number(button.dataset.edit||button.dataset.delete),tag=tags.find(t=>t.id===id);if(button.dataset.edit){$('tag-id').value=id;$('tag-name').value=tag.name;$('tag-category').value=tag.category;$('tag-form-title').textContent='Modifier le tag';$('tag-cancel').hidden=false;$('tag-name').focus();return;}if(!confirm(`Désactiver « ${tag.name} » pour les futures suggestions ?`))return;button.disabled=true;try{await api(cfg.tags+id+'/',{},'DELETE');await loadTags();toast('Tag désactivé.');}catch(error){toast(error.message);button.disabled=false;}});
const selectedId=new URLSearchParams(location.search).get('media');
if(section==='learning'&&selectedId){const a=assets.find(a=>a.public_id===selectedId);if(a){filter=a.tags_validated?'validated':'pending';limit=assets.length;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x.dataset.filter===filter));}}
render();if(section==='tags'||section==='learning')loadTags().catch(e=>toast(e.message));
if(selectedId){const index=assets.findIndex(a=>a.public_id===selectedId);document.getElementById('media-'+index)?.scrollIntoView();}

function facetHtml(a){const fields={objects:'Objets',people:'Personnes',places:'Lieux',colors:'Couleurs',concepts:'Concepts',visual_types:'Type de visuel',ocr:'Texte lu'};const values=Object.entries(fields).map(([key,label])=>{const list=a.ai_analysis?.[key]||a['ai_'+key]||[];return list.length?`<div class="facet-row"><strong>${label}</strong><span>${esc(list.join(', '))}</span></div>`:'';}).join('');return values?`<details class="analysis-facets"><summary>Voir les éléments reconnus par l’IA</summary>${values}</details>`:'';}
let feedbackTarget=null;
if(section==='learning'){
 const dialog=document.createElement('dialog');dialog.id='feedback-dialog';dialog.className='feedback-dialog';dialog.innerHTML=`<form id="feedback-form"><h2 id="feedback-title">Corriger un tag</h2><p>Votre décision et sa raison sont mémorisées pour les prochaines analyses.</p><label for="feedback-tag">Tag</label><input id="feedback-tag" maxlength="80" required><label for="feedback-reason">Pourquoi cette correction ?</label><select id="feedback-reason"><option>Objet absent de l’image</option><option>Identification incorrecte</option><option>Tag trop général</option><option>Doublon ou synonyme</option><option>Terme à corriger en français</option><option>Élément visible oublié par l’IA</option><option>Autre raison</option></select><label for="feedback-note">Précision (facultative)</label><textarea id="feedback-note" maxlength="350" placeholder="Ex. : il s’agit de dinde, pas de poulet."></textarea><p id="feedback-error" class="error" role="status"></p><div class="feedback-actions"><button class="button" type="button" id="feedback-cancel">Annuler</button><button class="button primary" type="submit">Mémoriser la correction</button></div></form>`;document.body.append(dialog);
 $('feedback-cancel').onclick=()=>dialog.close();
 $('feedback-form').onsubmit=async e=>{e.preventDefault();if(!feedbackTarget)return;const {a,action,tag}=feedbackTarget;const button=e.submitter;button.disabled=true;$('feedback-error').textContent='';const note=$('feedback-note').value.trim();if($('feedback-reason').value==='Autre raison'&&note.length<3){$('feedback-error').textContent='Précisez la raison de cette correction.';button.disabled=false;return;}try{const result=await api(cfg.feedback.replace('__ID__',encodeURIComponent(a.public_id)),{action,tag:action==='add'?$('feedback-tag').value:tag,replacement:$('feedback-tag').value,reason:$('feedback-reason').value+(note?' : '+note:'')});drafts.get(a.public_id).tags=result.tags;a.ai_tags=result.tags;dialog.close();render();toast('Correction mémorisée. Synchronisation Firebase programmée.');}catch(error){$('feedback-error').textContent=error.message;}finally{button.disabled=false;}};
 async function refreshLearning(){if(document.hidden)return;try{const response=await fetch(cfg.status);if(!response.ok)return;const payload=await response.json();$('worker-heading').textContent=payload.worker_alive?'✧ Analyse automatique active':'✧ File prête · en attente du service IA';$('worker-status').textContent=`${payload.queued} image(s) dans la file · ${payload.running} en cours · ${payload.firebase_pending} synchronisation(s) Firebase en attente`;let changed=false;for(const fresh of payload.assets){const a=assets.find(a=>a.public_id===fresh.public_id);if(!a)continue;const card=document.querySelector(`[data-index="${assets.indexOf(a)}"]`);if(card?.contains(document.activeElement)||feedbackTarget&&$('feedback-dialog').open&&feedbackTarget.a.public_id===a.public_id)continue;if(fresh.ai_analyzed_at!==a.ai_analyzed_at){Object.assign(a,fresh);const d=drafts.get(a.public_id);d.title=fresh.ai_title||d.title;d.description=fresh.ai_caption||'';d.tags=[...fresh.ai_tags];changed=true;}else if(fresh.media_status!==a.media_status||fresh['analysis_job__error']!==a['analysis_job__error']){Object.assign(a,fresh);changed=true;}}if(changed)render();}catch{}}
 setInterval(refreshLearning,12000);refreshLearning();
}
function openFeedback(a,action,tag){feedbackTarget={a,action,tag};$('feedback-title').textContent=action==='remove'?'Retirer ce tag':action==='replace'?'Corriger ce tag':'Ajouter un tag';$('feedback-tag').value=tag;$('feedback-tag').readOnly=action==='remove';$('feedback-reason').value=action==='add'?'Élément visible oublié par l’IA':action==='replace'?'Identification incorrecte':'Objet absent de l’image';$('feedback-note').value='';$('feedback-error').textContent='';$('feedback-dialog').showModal();}
