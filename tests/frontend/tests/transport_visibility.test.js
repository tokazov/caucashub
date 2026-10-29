import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

function render(path, offers, language='ru') {
  const code=readFileSync(new URL('../../../'+path,import.meta.url),'utf8');
  const start=code.indexOf('function renderTransportOffers()');
  const end=code.indexOf('// Открыть модалку отклика',start);
  const nodes={transportCount:{},transportList:{}};
  const context={
    document:{getElementById:id=>nodes[id]},
    window:{requestAnimationFrame:cb=>cb()},
    performance:{now:()=>0},console:{log:()=>{}},
    _transportOffers:offers,_transportTotal:offers.length,lang:language,
    TRANSLATIONS:{
      ru:{transport_count_suffix:'предложений',transport_confirm_availability:'Уточнить доступность'},
      ka:{transport_count_suffix:'შეთავაზება',transport_confirm_availability:'დააზუსტეთ ხელმისაწვდომობა'}
    },
    getToken:()=>null,esc:value=>String(value),getTypeLabel:()=> 'Тент'
  };
  vm.createContext(context);
  vm.runInContext(code.slice(start,end)+'\nrenderTransportOffers();',context);
  return {html:nodes.transportList.innerHTML,count:nodes.transportCount.textContent};
}

for(const path of ['main.js','frontend/main.js']) {
  const old={id:17,company_name:'Existing carrier',from_city:'Tbilisi',to_city:'Batumi',
    truck_type:'tent',available_from:'2026-07-01T00:00:00Z',urgent:true,dates_expired:true};
  for(const [language,label] of [['ru','Уточнить доступность'],['ka','დააზუსტეთ ხელმისაწვდომობა']]) {
    test(path+': expired carrier stays visible in '+language,()=>{
      const {html,count}=render(path,[old],language);
      assert.match(html,/Existing carrier/);
      assert.match(html,/Tbilisi/);
      assert.equal(count.startsWith('1 '),true);
      assert.equal(html.split(label).length-1,2); // Desktop and mobile.
      assert.doesNotMatch(html,/badge-urgent-new/);
      assert.doesNotMatch(html,/01\.07/);
    });
  }
  test(path+': current availability and urgency remain visible',()=>{
    const {html}=render(path,[{...old,dates_expired:false,availability_status:'confirmed'}]);
    assert.match(html,/badge-urgent-new/);
    assert.match(html,/01\.07/);
    assert.doesNotMatch(html,/Уточнить доступность/);
  });
}
