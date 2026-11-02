import * as THREE from 'three';
import {OrbitControls} from './assets/OrbitControls.js';

export function createFactory(container,{hero=false,onSelect=()=>{}}={}){
 const scene=new THREE.Scene();scene.background=new THREE.Color(0xf5f5ee);
 const camera=new THREE.OrthographicCamera(-20,20,12,-12,.1,200);camera.position.set(24,20,28);camera.lookAt(0,0,0);
 const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));renderer.outputColorSpace=THREE.SRGBColorSpace;container.appendChild(renderer.domElement);
 const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,1,0);controls.enableDamping=true;controls.dampingFactor=.08;controls.minZoom=.65;controls.maxZoom=2.6;controls.maxPolarAngle=Math.PI/2.05;controls.minPolarAngle=.08;controls.enablePan=false;
 scene.add(new THREE.AmbientLight(0xffffff,2));const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(-8,20,12);scene.add(light);
 const pale=new THREE.MeshStandardMaterial({color:0xdedfd5,roughness:.9,metalness:.12});const white=new THREE.MeshStandardMaterial({color:0xefefe5,roughness:.7});const dark=new THREE.MeshStandardMaterial({color:0x586052,roughness:.65,metalness:.35});const orange=new THREE.MeshStandardMaterial({color:0xed481d,roughness:.8});
 // Monochrome drafting surfaces: paper, cross-hatching and crisp ink edges.
 pale.color.setHex(0xe9eadf);white.color.setHex(0xf4f3e9);dark.color.setHex(0xa5ad9b);
 for(const material of [pale,white,dark]){material.metalness=0;material.roughness=1;material.polygonOffset=true;material.polygonOffsetFactor=1;material.polygonOffsetUnits=1;material.onBeforeCompile=shader=>{
 shader.fragmentShader=shader.fragmentShader.replace('#include <dithering_fragment>',`#include <dithering_fragment>
 float draftingShade = 1.0 - max(dot(normalize(normal),normalize(vec3(0.3,0.8,0.6))),0.0);
 float pencilLine = 1.0 - smoothstep(0.0,1.0,mod(gl_FragCoord.x+gl_FragCoord.y,7.0));
 float crossLine = 1.0 - smoothstep(0.0,0.75,mod(gl_FragCoord.x-gl_FragCoord.y,11.0));
 gl_FragColor.rgb = mix(gl_FragColor.rgb,vec3(0.24,0.27,0.21),(pencilLine*0.18+crossLine*0.055)*draftingShade);`);
 };}
 const edgeMat=new THREE.LineBasicMaterial({color:0x343c2c,transparent:true,opacity:.85});
 const hiddenInk=new THREE.LineBasicMaterial({color:0x5a6450,transparent:true,opacity:.045,depthTest:false,depthWrite:false});const groups=[],pickables=[],products=[],arms=[];let selected=0,running=!matchMedia('(prefers-reduced-motion: reduce)').matches,parallel=false,visible=true;
 const line=new THREE.Group();scene.add(line);
 const media=matchMedia('(prefers-reduced-motion: reduce)');let motionEnabled=document.documentElement.dataset.motion?document.documentElement.dataset.motion==='running':!media.matches;running=motionEnabled;controls.enableDamping=motionEnabled;
 let revealTime=motionEnabled?0:1.2,clock=0,cameraTween=null;
 const revealPlane=new THREE.Plane(new THREE.Vector3(-1,0,0),-17);renderer.clippingPlanes=motionEnabled?[revealPlane]:[];
 const labels=[];const machineNames=['CNC CUTTING','DRILLING','ASSEMBLY','INSPECTION','PACKAGING'];
 const onMotion=e=>{motionEnabled=e.detail.enabled;running=motionEnabled;controls.enableDamping=motionEnabled;if(!motionEnabled){renderer.clippingPlanes=[];revealTime=1.2;if(cameraTween){camera.position.copy(cameraTween.to);controls.target.copy(cameraTween.target);cameraTween=null;}}};
 document.addEventListener('realityloop:motion',onMotion);
 controls.addEventListener('start',()=>{cameraTween=null});
 function moveCamera(to,target=new THREE.Vector3(0,1,0)){if(!motionEnabled){camera.position.copy(to);controls.target.copy(target);controls.update();return;}cameraTween={from:camera.position.clone(),to,target,fromTarget:controls.target.clone(),elapsed:0};}
 function draftingLine(points,dashed=false){const geometry=new THREE.BufferGeometry().setFromPoints(points.map(p=>new THREE.Vector3(...p)));const material=dashed?new THREE.LineDashedMaterial({color:0x98a18c,dashSize:.16,gapSize:.12,transparent:true,opacity:.55}):new THREE.LineBasicMaterial({color:0x89927e,transparent:true,opacity:.7});const l=new THREE.Line(geometry,material);if(dashed)l.computeLineDistances();line.add(l);return l;}
 
 function box(parent,w,h,d,x,y,z,mat=pale){const geom=new THREE.BoxGeometry(w,h,d),m=new THREE.Mesh(geom,mat);m.position.set(x,y,z);m.add(new THREE.LineSegments(new THREE.EdgesGeometry(geom),edgeMat));m.add(new THREE.LineSegments(new THREE.EdgesGeometry(geom),hiddenInk));parent.add(m);return m}
 function cyl(parent,r,h,x,y,z,mat=dark,rotate=false){const geom=new THREE.CylinderGeometry(r,r,h,16),m=new THREE.Mesh(geom,mat);m.position.set(x,y,z);if(rotate)m.rotation.z=Math.PI/2;m.add(new THREE.LineSegments(new THREE.EdgesGeometry(geom,25),edgeMat));parent.add(m);return m}
 box(line,30,.3,9,0,-.2,0,white);
 const grid=new THREE.GridHelper(40,40,0xc8cdbf,0xe0e3d9);grid.position.y=-.38;scene.add(grid);
 // Conveyor, rails, support feet and individual roller cylinders.
 box(line,28,.16,1.15,0,.95,1.5,dark);for(let x=-13.5;x<=13.5;x+=.43)cyl(line,.08,1.07,x,1.08,1.5,pale,true).rotation.set(Math.PI/2,0,0);
 for(const z of [.82,2.18])box(line,28,.1,.07,0,1.15,z,dark);
 for(let x=-13;x<=13;x+=2.5){box(line,.12,1,.12,x,.45,1.02,dark);box(line,.12,1,.12,x,.45,1.98,dark)}
 function makeMachine(i){const g=new THREE.Group();g.position.x=(i-2)*5.5;line.add(g);groups.push(g);g.userData.index=i;
 box(g,3.6,.35,3.2,0,.3,0);for(const x of [-1.4,1.4])for(const z of [-1.1,1.1])box(g,.18,.4,.18,x,0,z,dark);
 if(i===0){box(g,3.5,2.5,2.2,0,1.7,-.25);box(g,2.4,1.75,.08,0,1.85,.89,dark);box(g,2.12,1.5,.09,0,1.85,.95,pale);box(g,.06,1.7,.12,0,1.8,1.02);box(g,.45,.75,.18,1.45,1.8,1.07,dark);box(g,.3,.3,.03,1.45,2,1.18,orange);for(let j=0;j<7;j++)box(g,.8,.025,.025,-.85,2.45-j*.12,-1.37,dark);cyl(g,.25,.7,0,3.15,-.2)}
 if(i===1){for(const x of [-1.35,1.35])box(g,.22,3,.35,x,1.85,-.65);box(g,3.1,.35,.65,0,3.3,-.65);box(g,1.0,.8,.7,0,2.8,-.35);cyl(g,.15,1,0,2,-.1);box(g,2.5,.18,1.8,0,1.4,.1,dark);box(g,.55,.5,.55,0,1.72,.1);box(g,.6,.7,.2,1.58,2.3,.05,dark);box(g,.42,.35,.03,1.58,2.43,.18,orange)}
 if(i===2){box(g,3,.15,2.7,0,.65,0);cyl(g,.7,.4,0,1,0);const arm=new THREE.Group();arm.position.set(0,1.25,0);g.add(arm);cyl(arm,.32,.8,0,.1,0,pale,true);const upper=box(arm,.44,1.8,.5,-.38,.9,0,white);upper.rotation.z=-.45;cyl(arm,.3,.6,-.75,1.75,0,dark,true);const fore=box(arm,1.4,.35,.4,-.12,2.05,0,white);fore.rotation.z=.35;box(arm,.3,.7,.3,.55,2,0,dark);arms.push(arm);
 for(const x of [-1.8,1.8])for(const z of [-1.5,1.5])box(g,.09,3.7,.09,x,2,z,dark);for(const z of [-1.5,1.5])box(g,3.7,.09,.09,0,3.85,z,dark);for(const x of [-1.8,1.8])box(g,.09,.09,3,x,3.85,0,dark);box(g,.3,.3,.1,1.65,3.2,1.56,orange)}
 if(i===3){for(const x of [-1.3,1.3])box(g,.3,2.8,.4,x,1.8,.2);box(g,3,.4,.7,0,3.05,.2);box(g,.65,.5,.65,0,2.75,.2,dark);box(g,.42,.1,.42,0,2.45,.2,orange);box(g,1.1,1.3,.6,-1.7,1.6,-.7);box(g,.85,.65,.05,-1.7,1.8,-.34,dark)}
 if(i===4){box(g,3.5,2.5,2.5,0,1.8,0);box(g,2.2,1.6,.12,0,1.5,1.31,dark);box(g,1.3,.8,.8,0,1.25,1.3,white);box(g,.5,.6,.12,1.3,2.5,1.31,dark);for(let a=0;a<2;a++)for(let b=0;b<2;b++)box(g,.7,.55,.7,2.2+a*.78,.55+b*.58,-.2,white)}
 // Fasteners, baseplate seams, vents and control wiring add drawn mechanical detail.
 for(const x of [-1.45,1.45])for(const z of [-1.2,1.2])cyl(g,.055,.055,x,.51,z,dark);
 for(let j=0;j<9;j++)box(g,.28,.022,.025,1.6,.7+j*.09,-1.13,dark);
 const conduit=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(1.6,.6,-1.2),new THREE.Vector3(1.6,2,-1.2),new THREE.Vector3(.8,2,-1.2)]);g.add(new THREE.Line(conduit,edgeMat));
 cyl(g,.09,.45,1.3,3.9,-.7,orange);
 const label=document.createElement('div');label.className='drafting-label';label.innerHTML=`<b>0${i+1}</b><span>${machineNames[i]}</span>`;container.appendChild(label);labels.push({el:label,point:new THREE.Vector3(g.position.x,5.25,-.1)});
 draftingLine([[g.position.x,4.4,-.1],[g.position.x,5.05,-.1]]);
 draftingLine([[g.position.x,-.01,-4.1],[g.position.x,4.3,-4.1],[g.position.x,4.3,.4]],true);
 pickables.push(g);return g;}
 for(let i=0;i<5;i++)makeMachine(i);
 draftingLine([[-14,.01,3.5],[14,.01,3.5]]);
 for(let x=-14;x<=14;x+=2)draftingLine([[x-.14,.01,3.26],[x+.14,.01,3.74]]);
 draftingLine([[-14,.02,-3.8],[14,.02,-3.8]],true);
 const sheetNote=document.createElement('div');sheetNote.className='drafting-note';sheetNote.textContent='AXONOMETRIC STUDY / SCHEMATIC MODEL';container.appendChild(sheetNote);
 const extra=groups[1].clone(true);extra.position.set(-5.5,0,-3.7);extra.visible=false;line.add(extra);extra.userData.index=1;pickables.push(extra);
 const selection=new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(4.2,.04,3.7)),new THREE.LineBasicMaterial({color:0xed481d}));selection.position.set(-11,.52,0);line.add(selection);
 for(let i=0;i<12;i++){const p=box(line,.48,.28,.45,-13+i*2.3,1.3,1.5,i===4?orange:white);products.push(p)}
 const ray=new THREE.Raycaster(),pointer=new THREE.Vector2();let down;
 renderer.domElement.addEventListener('pointerdown',e=>{down={x:e.clientX,y:e.clientY}});
 renderer.domElement.addEventListener('pointerup',e=>{if(!down||Math.hypot(e.clientX-down.x,e.clientY-down.y)>6)return;const rect=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);ray.setFromCamera(pointer,camera);const hit=ray.intersectObjects(pickables.filter(x=>x.visible),true)[0];if(hit){let node=hit.object;while(node&&node.userData.index===undefined)node=node.parent;if(node){select(node.userData.index);onSelect(node.userData.index)}}});
 function select(i){selected=i;if(!motionEnabled)selection.position.x=groups[i].position.x;labels.forEach((l,j)=>l.el.classList.toggle('selected',i===j));}
 function reset(){moveCamera(new THREE.Vector3(hero?23:22,hero?17:22,hero?27:30));camera.zoom=1;camera.updateProjectionMatrix();controls.update()}
 function resize(){const width=container.clientWidth,height=container.clientHeight;if(!width||!height)return;const aspect=width/height;const half=aspect<1.4?17/aspect:10;camera.left=-half*aspect;camera.right=half*aspect;camera.top=half;camera.bottom=-half;camera.updateProjectionMatrix();renderer.setSize(width,height,false)}
 new ResizeObserver(resize).observe(container);const observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting},{rootMargin:'150px'});observer.observe(container);
 container.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','-','='].includes(e.key))return;e.preventDefault();if(['+','='].includes(e.key))camera.zoom=Math.min(2.6,camera.zoom*1.1);else if(e.key==='-')camera.zoom=Math.max(.65,camera.zoom/1.1);else {const angle=e.key==='ArrowLeft'?.1:e.key==='ArrowRight'?-.1:0;camera.position.applyAxisAngle(new THREE.Vector3(0,1,0),angle);if(e.key==='ArrowUp')camera.position.y+=1;if(e.key==='ArrowDown')camera.position.y=Math.max(2,camera.position.y-1)}camera.updateProjectionMatrix();controls.update()});
 let last=performance.now();const projected=new THREE.Vector3();
 function animate(now){requestAnimationFrame(animate);const dt=Math.min((now-last)/1000,.05);last=now;if(!visible||document.hidden)return;
 if(motionEnabled&&revealTime<1.2){revealTime+=dt;revealPlane.constant=-17+35*Math.min(revealTime/1.2,1);if(revealTime>=1.2)renderer.clippingPlanes=[];}
 if(cameraTween){cameraTween.elapsed+=dt;const t=Math.min(cameraTween.elapsed/.7,1),ease=1-Math.pow(1-t,3);camera.position.lerpVectors(cameraTween.from,cameraTween.to,ease);controls.target.lerpVectors(cameraTween.fromTarget,cameraTween.target,ease);if(t===1)cameraTween=null;}
 if(running&&motionEnabled){clock+=dt;for(const p of products){p.position.x+=dt*1.1;if(p.position.x>13.4)p.position.x=-13.4}for(const a of arms)a.rotation.y=Math.sin(clock*.7)*.3;}
 selection.position.x=THREE.MathUtils.lerp(selection.position.x,groups[selected].position.x,motionEnabled?Math.min(dt*9,1):1);
 controls.update();renderer.render(scene,camera);
 for(const label of labels){projected.copy(label.point).project(camera);label.el.style.left=((projected.x*.5+.5)*container.clientWidth)+'px';label.el.style.top=((-projected.y*.5+.5)*container.clientHeight)+'px';label.el.style.visibility=projected.z>1||Math.abs(projected.x)>1.05||revealTime<.8?'hidden':'visible';}
 }
 camera.position.set(hero?23:22,hero?17:22,hero?27:30);select(0);controls.update();resize();requestAnimationFrame(animate);
 return {select,reset,setParallel(value){parallel=value;extra.visible=value},setView(view){if(view==='top'){moveCamera(new THREE.Vector3(.01,40,.01),new THREE.Vector3(0,0,0));camera.zoom=1;camera.updateProjectionMatrix();controls.update()}else reset()},toggle(){if(!motionEnabled)return false;running=!running;return running},get running(){return running}};
}
