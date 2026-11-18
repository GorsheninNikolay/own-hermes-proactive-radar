const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const src = fs.readFileSync('desktop/plugin.js','utf8');
const body = src.slice(src.indexOf('const BOARD_KEY'),src.indexOf('export default'));
const hook = {useState: x => [typeof x === 'function' ? x() : x, ()=>{}], useEffect: ()=>{}, useMemo: f=>f(), useRef: ()=>({current:null})};
const element = (type,props)=>({type,props:props||{}});
function context() { return {console, ...hook, jsx:element, jsxs:element, Fragment:'fragment', Badge:'badge', Button:'button', ScrollArea:'scroll', Skeleton:'skeleton', SandboxedFrame:'iframe', cn: (...x)=>x.filter(Boolean).join(' '), relativeTime:()=>'', queryClient:{invalidateQueries(){}}, useQuery:()=>({data:{language:'ru-RU',tasks:[]},isLoading:false}), window:{addEventListener(){}, removeEventListener(){}}, document:{querySelector:()=>true}}; }
function verify(c) {
 vm.runInContext(`
 for (const locale of ['ru','ru-RU',' RU_ru ']) {
   if (normalizeLanguage(locale) !== 'ru') throw Error('locale '+locale);
 }
 if (normalizeLanguage('fr') !== 'en' || normalizeLanguage(null) !== 'es') throw Error('fallback');
 if (Object.keys(TEXT.en).some(k => !(k in TEXT.ru))) throw Error('missing Russian key');
 if (TEXT.ru.refresh !== 'Обновить') throw Error('Russian refresh');
 if (label({label:{ru:'Поездка',es:'Viaje'}},'ru-RU') !== 'Поездка') throw Error('kind locale');
 const p = Proposal({proposal:{id:'p1',status:'pending',action_class:'external',draft:'<raw approved draft>',options:[{id:'send',label:'Отправить'}]},t:TEXT.ru,onFeedback(){}});
 globalThis.proposal = p;
 const task = {id:'t1',title:'Поездка',status:'open',checklist:[{item:'outbound transport booked',label:'транспорт туда забронирован',status:'missing'},{item:'<custom>',label:'<custom>',status:'missing'}]};
 globalThis.focus = Focus({task,kind:{icon:'',label:{ru:'Поездка'}},t:TEXT.ru,language:'ru',onClose(){},onFeedback(){},onDismiss(){}});
 `,c);
 const nodes=[]; function walk(n){if(!n)return; if(Array.isArray(n)){n.forEach(walk);return;} if(typeof n==='object'){nodes.push(n);walk(n.props?.children)}} walk(c.proposal);
 assert(nodes.some(n=>n.props?.children==='Внешнее действие'));
 assert(nodes.some(n=>Array.isArray(n.props?.children)&&n.props.children.includes('<raw approved draft>')));
 assert(!nodes.some(n=>n.props?.dangerouslySetInnerHTML));
 walk(c.focus);
 assert(nodes.some(n=>Array.isArray(n.props?.children)&&n.props.children.includes('транспорт туда забронирован; <custom>')));
 assert(!nodes.some(n=>n.props?.dangerouslySetInnerHTML));
}
let c=vm.createContext(context()); vm.runInContext(body,c); verify(c);
const desktopContext = c;
let registered;
c=vm.createContext(context()); c.window.__HERMES_PLUGIN_SDK__={React:{createElement:element,Fragment:'fragment'},hooks:hook}; c.window.__HERMES_PLUGINS__={register:(id,page)=>{assert.equal(id,'hermes-proactive-radar');registered=page}};
let web=fs.readFileSync('dashboard/dist/index.js','utf8');
// Run the actual IIFE, exposing shared functions only for assertions inside its closure.
web=web.replace('/* wire the shimmed data layer */',`globalThis.verifyShared = () => { globalThis.TEXT = TEXT; globalThis.Focus = Focus; globalThis.Proposal = Proposal; globalThis.normalizeLanguage = normalizeLanguage; globalThis.label = label; };\n/* wire the shimmed data layer */`);
vm.runInContext(web,c); assert.equal(typeof registered,'function'); c.verifyShared(); assert.equal(c.TEXT.ru.refresh,'Обновить'); verify(c);
async function checkPayload() {
 const c = desktopContext;
 vm.runInContext("rest = async (path, init) => { globalThis.sentPayload = {path, ...init}; return {} }", c);
 const buttons=[]; function visit(n){ if(!n)return; if(Array.isArray(n))return n.forEach(visit); if(typeof n==='object'){if(n.props?.onClick)buttons.push(n);visit(n.props?.children)} }
 visit(c.proposal); await buttons[0].props.onClick();
 assert.equal(c.sentPayload.path,'/proposals/p1/respond'); assert.equal(c.sentPayload.body.option,'send');
}
checkPayload().then(()=>console.log('desktop payload unchanged: PASS'));
console.log('desktop shared body + actual web IIFE: PASS');
