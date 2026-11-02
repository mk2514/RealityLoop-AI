// Progressive enhancement: the page stays readable if motion APIs are absent.
const media=window.matchMedia('(prefers-reduced-motion: reduce)');
const root=document.documentElement,button=document.getElementById('page-motion');
let enabled=!media.matches;
const activeAnimations=new Set();
function play(element,keyframes,options={}){
 if(!enabled||!element?.animate)return;
 const animation=element.animate(keyframes,{duration:520,easing:'cubic-bezier(.2,.7,.2,1)',...options});
 activeAnimations.add(animation);animation.finished.then(()=>activeAnimations.delete(animation)).catch(()=>activeAnimations.delete(animation));return animation;
}
function applyMotion(value){enabled=value;root.dataset.motion=enabled?'running':'paused';button.textContent=enabled?'PAUSE EFFECTS':'RESUME EFFECTS';button.setAttribute('aria-pressed',String(!enabled));
 if(!enabled){for(const animation of activeAnimations)animation.cancel();activeAnimations.clear()}
 document.dispatchEvent(new CustomEvent('realityloop:motion',{detail:{enabled}}));
}
button.onclick=()=>applyMotion(!enabled);
media.addEventListener('change',e=>applyMotion(!e.matches));applyMotion(enabled);
for(const [i,element] of [...document.querySelectorAll('.nav,.hero-bottom h1,.hero-copy')].entries())play(element,[{opacity:.35,transform:'translateY(10px)'},{opacity:1,transform:'translateY(0)'}],{delay:i*70,duration:650});
if('IntersectionObserver' in window){const observer=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;play(entry.target,[{opacity:.55,transform:'translateY(14px)'},{opacity:1,transform:'translateY(0)'}]);observer.unobserve(entry.target)}},{threshold:.12});document.querySelectorAll('.section-top,.trust-copy,.validation-panel,.closing,.footer-grid').forEach(el=>observer.observe(el));}
// Draw only the observed curve, preserving dashed reference and threshold lines.
function drawChart(element){const path=element.querySelector('path[stroke="#343b2d"]');if(!path?.getTotalLength)return;try{const length=path.getTotalLength();if(!Number.isFinite(length)||length<=0)return;play(path,[{strokeDasharray:`${length} ${length}`,strokeDashoffset:length},{strokeDasharray:`${length} ${length}`,strokeDashoffset:0}],{duration:560})}catch{}}
let chartTimers=new Map();const chartObserver=new MutationObserver(entries=>{for(const entry of entries){const el=entry.target;clearTimeout(chartTimers.get(el));chartTimers.set(el,setTimeout(()=>{drawChart(el);chartTimers.delete(el)},90))}});
document.querySelectorAll('#sensor-chart,#trust-chart').forEach(el=>{chartObserver.observe(el,{childList:true});drawChart(el)});
const resultObserver=new MutationObserver(entries=>{for(const el of new Set(entries.map(e=>e.target)))play(el,[{opacity:.4,transform:'translateY(3px)'},{opacity:1,transform:'translateY(0)'}],{duration:240})});
document.querySelectorAll('#baseline-output,#proposed-output,#decision-status').forEach(el=>resultObserver.observe(el,{childList:true}));
const dialogObserver=new MutationObserver(entries=>{for(const e of entries)if(e.target.open)play(e.target,[{opacity:0,transform:'translateY(12px)'},{opacity:1,transform:'translateY(0)'}],{duration:200})});document.querySelectorAll('dialog').forEach(el=>dialogObserver.observe(el,{attributes:true,attributeFilter:['open']}));
let frame;function progress(){cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{const max=root.scrollHeight-window.innerHeight,ratio=max>0?Math.max(0,Math.min(1,window.scrollY/max)):0;document.querySelector('.reading-progress').style.transform=`scaleX(${ratio})`})}window.addEventListener('scroll',progress,{passive:true});window.addEventListener('resize',progress);progress();

for(const section of document.querySelectorAll('.section-top')){
 const rule=document.createElement('i');rule.className='draft-rule';rule.setAttribute('aria-hidden','true');section.append(rule);
 if('IntersectionObserver' in window){const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){play(rule,[{transform:'scaleX(0)',opacity:1},{transform:'scaleX(1)',opacity:.75},{transform:'scaleX(1)',opacity:0}],{duration:850});observer.disconnect()}});observer.observe(section)}
}
