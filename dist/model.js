export const machines = [
 {name:'CNC cutting',cycle:8,component:'Spindle motor',description:'Cuts incoming stock to size before drilling. The sample model uses one cutting station.'},
 {name:'Drilling',cycle:14,component:'Drill spindle',description:'The initial bottleneck. A second compatible drilling station shares the load in the proposed configuration.'},
 {name:'Assembly',cycle:11,component:'Robot drive',description:'Assembles the prepared parts. Its cycle becomes the constraint once drilling capacity increases.'},
 {name:'Inspection',cycle:7,component:'Inspection sensor',description:'Checks completed assemblies before packaging. Quality rejection is outside this capacity model.'},
 {name:'Packaging',cycle:9,component:'Conveyor motor',description:'Prepares completed parts for dispatch. The material flow remains in the same process order.'}
];
export function capacity({cycle=14,downtime=5,demand=400,parallel=true,chaos='none'}={}){
 const requested=demand*(chaos==='demand'?1.3:1),available=(1-downtime/100)*(chaos==='delay'?.8:1);
 const assembly=chaos==='failure'?22:11;
 const base=[8,cycle,assembly,7,9],proposed=[8,cycle/(parallel?2:1),assembly,7,9];
 const calc=c=>{const bottleneck=Math.max(...c),index=c.indexOf(bottleneck);return {units:Math.floor(Math.min(requested,3600/bottleneck*available)),bottleneck:machines[index].name,cycle:bottleneck}};
 return {baseline:calc(base),proposed:calc(proposed),demand:requested,available};
}
export function sampleSeries(sensor='temperature',count=60){
 const values=[];for(let i=0;i<count;i++){const t=i/(count-1),bump=Math.exp(-Math.pow((t-.64)/.18,2));
 let expected,value,unit,threshold;
 if(sensor==='temperature'){expected=46+2*t;value=expected+18*bump+Math.sin(i*1.7)*.8;unit='°C';threshold=60}
 else if(sensor==='vibration'){expected=2.1;value=expected+1.7*bump+Math.sin(i*2.3)*.18;unit='mm/s';threshold=3.5}
 else if(sensor==='current'){expected=5.2;value=expected+1.4*bump+Math.sin(i*.9)*.15;unit='A';threshold=6.5}
 else {expected=11;value=expected+4*bump+Math.sin(i*.8)*.2;unit='s';threshold=14}
 values.push({value,expected,unit,threshold,timestamp:new Date(Date.UTC(2026,0,1,10,i)).toISOString()});}return values;
}
export function validation(calibrated=false){
 const observed=Array.from({length:60},(_,i)=>11+Math.sin(i*.7)*.23+Math.cos(i*.21)*.13);
 const fitted=observed.slice(0,40).reduce((a,b)=>a+b,0)/40,prediction=calibrated?fitted:8;
 const error=observed.slice(40).reduce((s,y)=>s+Math.abs(y-prediction),0)/20;
 return {observed,prediction,error,passed:error<=.6};
}
export function parseCSV(text){
 const lines=text.trim().split(/\r?\n/);if(lines.length<3)throw new Error('Provide a header and at least two readings.');
 if(lines.length>10001)throw new Error('Please use a CSV with at most 10,000 readings.');
 const head=lines[0].replace(/^\uFEFF/,'').toLowerCase().split(',').map(s=>s.trim());
 const ti=head.indexOf('timestamp'),vi=head.indexOf('temperature');if(ti<0||vi<0)throw new Error('CSV needs timestamp and temperature columns.');
 const seen=new Set();const readings=lines.slice(1).map((line,i)=>{const cells=line.split(','),timestamp=cells[ti]?.trim(),raw=cells[vi]?.trim(),value=Number(raw),time=Date.parse(timestamp);
 if(!timestamp||!raw||!Number.isFinite(value)||!Number.isFinite(time)||value< -50||value>300)throw new Error(`Invalid reading on row ${i+2}. Use valid dates and temperatures from -50 to 300 °C.`);
 if(seen.has(time))throw new Error(`Duplicate timestamp on row ${i+2}.`);seen.add(time);return {timestamp:new Date(time).toISOString(),value,unit:'°C',threshold:60,expected:48};});
 return readings.sort((a,b)=>Date.parse(a.timestamp)-Date.parse(b.timestamp));
}
