"""Wire explicit role/name decisions into Framework7 v4 profile apply."""
from __future__ import annotations

import pathlib
import sys


def replace_exact(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"{label}: expected {count} anchor(s), found {found}")
    return text.replace(old, new)


def patch_entry(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "install_profile_decisions" in text:
        return
    text = replace_exact(
        text,
        "from JARNSEN_FRAMEWORK7_FEATURE_HARDENING import install_feature_hardening\n",
        "from JARNSEN_FRAMEWORK7_FEATURE_HARDENING import install_feature_hardening\n"
        "from JARNSEN_FRAMEWORK7_PROFILE_DECISIONS import install_profile_decisions\n",
        "profile decision import",
        2,
    )
    text = replace_exact(
        text,
        "        install_feature_hardening(base.LegacyBridge, base.ApiHandler)\n        install_runtime_fixes(base)\n",
        "        install_feature_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "        install_profile_decisions(base.LegacyBridge)\n"
        "        install_runtime_fixes(base)\n",
        "early profile decision install",
    )
    text = replace_exact(
        text,
        "install_feature_hardening(base.LegacyBridge, base.ApiHandler)\ninstall_runtime_fixes(base)\n",
        "install_feature_hardening(base.LegacyBridge, base.ApiHandler)\n"
        "install_profile_decisions(base.LegacyBridge)\n"
        "install_runtime_fixes(base)\n",
        "frontend profile decision install",
    )
    path.write_text(text, encoding="utf-8")


def patch_frontend(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "profileDecisionDialog" in text:
        return
    old = '''  async function profileAction(command){const n=selectedNode();if(!n)throw new Error('Keine Node ausgewählt.');const payload={command,slot:profileSlot,node_id:n.node_id,long_name:'',short_name:'',pin:'240180',transport:'Automatisch',apply_pin:true,apply_psk:false};const r=await request('/api/profile/action',{method:'POST',body:JSON.stringify(payload)});toast(r.message||'Profilaktion gestartet');}\n'''
    new = r'''  function profileDecisionDialog(title, text, choices) {
    return new Promise(resolve => {
      document.querySelector('.neo-profile-decision-overlay')?.remove();
      const overlay=document.createElement('div');overlay.className='neo-profile-decision-overlay';
      overlay.style.cssText='position:fixed;inset:0;z-index:10050;background:rgba(3,10,18,.78);display:grid;place-items:center;padding:24px;backdrop-filter:blur(8px)';
      const card=document.createElement('div');card.style.cssText='width:min(520px,92vw);background:#101e2a;border:1px solid #29455a;border-radius:18px;padding:24px;box-shadow:0 24px 80px rgba(0,0,0,.45);color:#eaf5ff';
      card.innerHTML=`<h3 style="margin:0 0 8px;font-size:18px">${esc(title)}</h3><p style="margin:0 0 18px;color:#9db4c5;line-height:1.45">${esc(text)}</p><div class="neo-profile-decision-actions" style="display:grid;grid-template-columns:repeat(${Math.max(1,choices.length)},minmax(0,1fr));gap:10px"></div><button type="button" data-profile-cancel style="margin-top:12px;width:100%;border:0;background:transparent;color:#8fa7b9;padding:8px;cursor:pointer">Abbrechen</button>`;
      const actions=card.querySelector('.neo-profile-decision-actions');
      choices.forEach(choice=>{const button=document.createElement('button');button.type='button';button.className='neo-btn primary';button.style.cssText='min-height:46px;white-space:normal';button.textContent=choice.label;button.addEventListener('click',()=>{overlay.remove();resolve(choice.value);});actions.appendChild(button);});
      card.querySelector('[data-profile-cancel]').addEventListener('click',()=>{overlay.remove();resolve(null);});overlay.addEventListener('click',event=>{if(event.target===overlay){overlay.remove();resolve(null);}});overlay.appendChild(card);document.body.appendChild(overlay);
    });
  }

  async function profileAction(command){
    const n=selectedNode();if(!n)throw new Error('Keine Node ausgewählt.');
    const payload={command,slot:profileSlot,node_id:n.node_id,long_name:'',short_name:'',pin:'240180',transport:'Automatisch',apply_pin:true,apply_psk:false};
    if(command==='apply'){
      const preflight=await request('/api/profile/action',{method:'POST',body:JSON.stringify({...payload,command:'preflight'})});
      if(preflight.role_mismatch){
        const current=String(preflight.current_role||'').trim();const desired=String(preflight.profile_role||'').trim();
        const choice=await profileDecisionDialog('Welche Rolle soll geschrieben werden?',`Aktuell auf ${n.long_name||n.node_id}: ${current}. Im Grundprofil ${preflight.profile_name||''}: ${desired}.`,[{label:current,value:current},{label:desired,value:desired}]);
        if(choice==null)return;payload.role_choice=choice;
      }else if(preflight.profile_role){payload.role_choice=preflight.profile_role;}
      for(const change of (preflight.name_changes||[])){
        const keep=change.old||'bisherigen Namen behalten';const write=change.new||'neuen Namen schreiben';
        const choice=await profileDecisionDialog(`${change.field} ändern?`,`Alt: ${change.old||'—'} · Neu: ${change.new||'—'}`,[{label:keep,value:'old'},{label:write,value:'new'}]);
        if(choice==null)return;
        if(choice==='old'){
          if(change.field==='Long Name')payload.long_name='';
          if(change.field==='Short Name')payload.short_name='';
        }else{payload.confirm_name_change=true;}
      }
    }
    const r=await request('/api/profile/action',{method:'POST',body:JSON.stringify(payload)});toast(r.message||'Profilaktion gestartet');
  }
'''
    if old not in text:
        raise RuntimeError("v4 profileAction anchor missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_build(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "        'tools/JARNSEN_FRAMEWORK7_FEATURE_HARDENING.py',\n"
    addition = "        'tools/JARNSEN_FRAMEWORK7_PROFILE_DECISIONS.py',\n"
    if addition not in text:
        if text.count(marker) != 1:
            raise RuntimeError("profile decision compile anchor missing")
        text = text.replace(marker, marker + addition, 1)
    capability_anchor = "        foreach ($capability in @('profile_provision_hardware_guard','profile_provision_preflight_bundle','ble_ota_source_preflight','ble_recovery_signature')) {\n            if (!$service.critical.$capability) { throw \"Feature critical capability missing: $capability\" }\n        }\n"
    if "profile_role_confirmation" not in text:
        addition = (
            "        foreach ($capability in @('profile_role_confirmation','profile_name_confirmation')) {\n"
            "            if (!$service.critical.$capability) { throw \"Profile decision capability missing: $capability\" }\n"
            "        }\n"
        )
        if text.count(capability_anchor) != 1:
            raise RuntimeError("profile decision capability anchor missing")
        text=text.replace(capability_anchor,capability_anchor+addition,1)
    path.write_text(text,encoding="utf-8")


def patch_validator(path: pathlib.Path) -> None:
    text=path.read_text(encoding="utf-8")
    if "test_profile_decision_contract" in text:return
    helper='''\n\ndef test_profile_decision_contract() -> None:\n    backend=(ROOT / "JARNSEN_FRAMEWORK7_PROFILE_DECISIONS.py").read_text(encoding="utf-8")\n    frontend=(ROOT / "service_tool_web" / "neo-ui-v400.js").read_text(encoding="utf-8")\n    for marker in ("current_role", "profile_role", "role_mismatch", "role_choice", "confirm_name_change", "_profile_with_role", "profiles[slot] = original"):\n        if marker not in backend:\n            raise AssertionError(f"profile decision backend marker missing: {marker}")\n    for marker in ("profileDecisionDialog", "Welche Rolle soll geschrieben werden?", "preflight.role_mismatch", "payload.role_choice", "Alt:", "Neu:"):\n        if marker not in frontend:\n            raise AssertionError(f"profile decision UI marker missing: {marker}")\n    print("OK profile role/name decisions")\n'''
    anchor="\ndef main() -> None:\n"
    if text.count(anchor)!=1:raise RuntimeError("profile decision validator main anchor missing")
    text=text.replace(anchor,helper+anchor,1)
    call="    test_safe_close_guard()\n"
    if call not in text:call="    test_build_smoke_contract()\n"
    text=text.replace(call,call+"    test_profile_decision_contract()\n",1)
    path.write_text(text,encoding="utf-8")


def main()->None:
    root=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else "tools")
    patch_entry(root/"JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py")
    patch_frontend(root/"service_tool_web"/"neo-ui-v400.js")
    patch_build(root/"ci"/"build_framework7_service_tool.ps1")
    patch_validator(root/"ci"/"validate_framework7_hardening_contracts.py")
    print("Applied Framework7 explicit profile role/name decisions")


if __name__=="__main__":main()
